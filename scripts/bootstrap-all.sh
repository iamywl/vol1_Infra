#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"

SSH_KEY="$(python3 -c 'import os,yaml; c=yaml.safe_load(open("'"$ROOT_DIR"'/infra/config/cluster.yaml")); print(os.path.expanduser(c["ssh"]["private_key_path"]))')"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

refresh_inventory() {
  "$ROOT_DIR/scripts/ops-vm-ctl.sh" sync-ips >/dev/null
  python3 - "$ROOT_DIR" <<'PY'
import os, sys, yaml

root = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(root, "infra/config/cluster.yaml")))
vm_ips = {}
for n in cfg["nodes"]:
    p = os.path.join(root, ".runtime/vm-ips", f"{n['name']}.ip")
    vm_ips[n["name"]] = open(p).read().strip()

ops_nodes = [n for n in cfg["nodes"] if n["role"] == "ops"]
cp_nodes  = [n for n in cfg["nodes"] if n["role"] == "control_plane"]
wk_nodes  = [n for n in cfg["nodes"] if n["role"] == "worker"]
ops_ip    = vm_ips[ops_nodes[0]["name"]]
ssh_key   = os.path.expanduser(cfg["ssh"]["private_key_path"])

hosts_lines = ["[ops]"]
for n in ops_nodes:
    hosts_lines.append(f"{n['name']} ansible_host={vm_ips[n['name']]}")
hosts_lines.append("\n[control_plane]")
for n in cp_nodes:
    b = str(n.get("bootstrap", False)).lower()
    hosts_lines.append(f"{n['name']} ansible_host={vm_ips[n['name']]} bootstrap_leader={b}")
hosts_lines.append("\n[worker]")
for n in wk_nodes:
    hosts_lines.append(f"{n['name']} ansible_host={vm_ips[n['name']]}")
hosts_lines.append(f"""
[k8s:children]
control_plane
worker

[all:vars]
ansible_user={cfg['ssh']['user']}
ansible_ssh_private_key_file={ssh_key}
ansible_python_interpreter=/usr/bin/python3
ansible_ssh_common_args=-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10
""")
open(os.path.join(root, "infra/ansible/inventories/hosts.ini"), "w").write("\n".join(hosts_lines))

gen = {
    "project_name": cfg["project"],
    "internal_domain": cfg["domain"],
    "ops_vm_name": ops_nodes[0]["name"],
    "ops_ip": ops_ip,
    "k8s_version": cfg["kubernetes"]["version"],
    "pod_cidr": cfg["kubernetes"]["pod_cidr"],
    "service_cidr": cfg["kubernetes"]["service_cidr"],
    "api_port": cfg["kubernetes"]["api_port"],
    "versions": cfg["versions"],
    "node_ips": vm_ips,
    "control_planes": [{"name": n["name"], "ip": vm_ips[n["name"]], "bootstrap": bool(n.get("bootstrap", False))} for n in cp_nodes],
    "workers": [{"name": n["name"], "ip": vm_ips[n["name"]]} for n in wk_nodes],
}
yaml.safe_dump(gen, open(os.path.join(root, "infra/ansible/inventories/generated.yml"), "w"), sort_keys=False)
print(f"[refresh-inventory] Updated hosts.ini & generated.yml (ops_ip={ops_ip})")
PY
}

sync_platform() {
  local OPS_IP VAULT_TOKEN CA_PEM REVIEWER_JWT
  OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"

  echo "[platform] Fetching Vault root token from macprod-ops..."
  VAULT_TOKEN="$(ssh $SSH_OPTS "admin@${OPS_IP}" "sudo jq -r '.root_token' /opt/macprod/vault/init.json")"

  echo "[platform] Creating Vault TokenReview ServiceAccount in Kubernetes..."
  kubectl -n kube-system create serviceaccount vault-token-reviewer --dry-run=client -o yaml | kubectl apply -f -
  kubectl create clusterrolebinding vault-token-reviewer-delegator \
    --clusterrole=system:auth-delegator \
    --serviceaccount=kube-system:vault-token-reviewer \
    --dry-run=client -o yaml | kubectl apply -f -
  REVIEWER_JWT="$(kubectl -n kube-system create token vault-token-reviewer --duration=8760h)"

  CA_PEM="$(python3 - "$KUBECONFIG" <<'PY'
import sys, yaml, base64
kc = yaml.safe_load(open(sys.argv[1]))
b64 = kc["clusters"][0]["cluster"]["certificate-authority-data"]
print(base64.b64decode(b64).decode(), end="")
PY
)"

  echo "[platform] Running Layer-2 Terraform (S3 backend on SeaweedFS + Vault + K8s Governance)..."
  cat >"$ROOT_DIR/.runtime/backend-s3.hcl" <<EOF
endpoint   = "http://${OPS_IP}:8333"
access_key = "macprod-s3-admin"
secret_key = "macprod-s3-secret-2026"
EOF

  (
    cd "$ROOT_DIR/infra/terraform/platform-state"
    terraform init -reconfigure -backend-config="$ROOT_DIR/.runtime/backend-s3.hcl"
    terraform apply -auto-approve \
      -var="vault_addr=http://${OPS_IP}:8200" \
      -var="vault_token=${VAULT_TOKEN}" \
      -var="kubeconfig_path=${KUBECONFIG}" \
      -var="k8s_api_endpoint=https://${OPS_IP}:6443" \
      -var="k8s_ca_cert=${CA_PEM}" \
      -var="vault_reviewer_jwt=${REVIEWER_JWT}"
  )

  echo "[platform] Configuring Vault SSH CA trust across all 7 VMs..."
  (
    cd "$ROOT_DIR/infra/ansible"
    ansible-playbook playbooks/05-configure-ssh-ca.yml
  )

  echo "[platform] Seeding S3 credentials Secrets for CloudNativePG (apps) and Velero (velero)..."
  kubectl -n apps create secret generic cnpg-s3-creds \
    --from-literal=ACCESS_KEY_ID=macprod-s3-admin \
    --from-literal=SECRET_ACCESS_KEY=macprod-s3-secret-2026 \
    --dry-run=client -o yaml | kubectl apply -f -

  cat >/tmp/macprod-velero-creds <<'EOF'
[default]
aws_access_key_id = macprod-s3-admin
aws_secret_access_key = macprod-s3-secret-2026
EOF
  kubectl -n velero create secret generic velero-cloud-credentials \
    --from-file=cloud=/tmp/macprod-velero-creds \
    --dry-run=client -o yaml | kubectl apply -f -
  rm -f /tmp/macprod-velero-creds

  echo "[platform] Building & pushing order-service:v1.0.0 to Zot registry on macprod-ops..."
  ssh $SSH_OPTS "admin@${OPS_IP}" "rm -rf /tmp/order-service-build && mkdir -p /tmp/order-service-build"
  scp $SSH_OPTS -r "$ROOT_DIR/apps/order-service/Dockerfile" \
    "$ROOT_DIR/apps/order-service/requirements.txt" \
    "$ROOT_DIR/apps/order-service/app" \
    "admin@${OPS_IP}:/tmp/order-service-build/"

  ssh $SSH_OPTS "admin@${OPS_IP}" "
    set -euo pipefail
    cd /tmp/order-service-build
    sudo docker build -t 127.0.0.1:5000/apps/order-service:v1.0.0 .
    sudo docker push 127.0.0.1:5000/apps/order-service:v1.0.0
  "

  if command -v trivy >/dev/null 2>&1; then
    echo "[platform] Running Trivy vulnerability scan on order-service:v1.0.0..."
    trivy image --insecure --severity HIGH,CRITICAL --exit-code 0 "${OPS_IP}:5000/apps/order-service:v1.0.0" || true
  fi

  echo "[platform] Pushing GitOps repository to local Gitea (http://gitea.macprod.internal:3000/macprod/gitops.git)..."
  local TMP_REPO="/tmp/macprod-gitops-push"
  rm -rf "$TMP_REPO"
  mkdir -p "$TMP_REPO/platform" "$TMP_REPO/apps"
  cp -R "$ROOT_DIR/platform/gitops" "$TMP_REPO/platform/gitops"
  cp -R "$ROOT_DIR/apps/order-service" "$TMP_REPO/apps/order-service"

  (
    cd "$TMP_REPO"
    git init -b main >/dev/null
    git config user.name "macprod-bot"
    git config user.email "devops@macprod.internal"
    git add -A
    git commit -m "chore(gitops): sync platform and order-service manifests" >/dev/null
    git push --force "http://macprod:MacprodGitOps2026!@${OPS_IP}:3000/macprod/gitops.git" main
  )
  rm -rf "$TMP_REPO"

  echo "[platform] Applying ArgoCD Root App-of-Apps (macprod-root)..."
  kubectl apply -f "$ROOT_DIR/platform/gitops/root-app.yaml"

  echo "[platform] Triggering immediate ArgoCD root refresh..."
  kubectl -n argocd annotate application macprod-root argocd.argoproj.io/refresh=hard --overwrite >/dev/null || true

  echo "[platform] Platform sync initiated. Checking ArgoCD Applications:"
  sleep 5
  kubectl -n argocd get applications
}

cmd="${1:-help}"
shift || true
case "$cmd" in
  refresh-inventory) refresh_inventory "$@" ;;
  sync-platform)     sync_platform "$@" ;;
  *)
    echo "Usage: $0 {refresh-inventory|sync-platform}"
    exit 1
    ;;
esac
