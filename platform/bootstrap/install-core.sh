#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"

if [[ ! -f "$KUBECONFIG" ]]; then
  echo "[bootstrap] ERROR: $KUBECONFIG not found. Run 'make k8s' first." >&2
  exit 1
fi

OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"
eval "$(python3 - "$ROOT_DIR/infra/config/cluster.yaml" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
v = c["versions"]
print(f'CILIUM_VER="{v["cilium"]}"')
print(f'GWAPI_VER="{v["gateway_api"]}"')
print(f'ARGOCD_VER="{v["argocd_chart"]}"')
print(f'ROLLOUTS_VER="{v["argo_rollouts_chart"]}"')
print(f'GW_PLUGIN_VER="{v["argo_rollouts_gwapi_plugin"]}"')
print(f'LPP_VER="{v["local_path_provisioner"]}"')
print(f'POD_CIDR="{c["kubernetes"]["pod_cidr"]}"')
PY
)"

echo "[bootstrap] Tagging worker nodes with node-role.kubernetes.io/worker=true..."
for wk in $(kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name | grep 'macprod-wk-'); do
  kubectl label node "$wk" node-role.kubernetes.io/worker=true --overwrite >/dev/null
done

echo "[bootstrap] Installing Gateway API CRDs (${GWAPI_VER} experimental) before Cilium..."
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GWAPI_VER}/experimental-install.yaml"

echo "[bootstrap] Adding Helm repositories..."
helm repo add cilium https://helm.cilium.io/ >/dev/null 2>&1 || true
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null

echo "[bootstrap] Installing Cilium ${CILIUM_VER} (eBPF kube-proxy replacement + Gateway API hostNetwork + Hubble)..."
cat >/tmp/macprod-cilium-values.yaml <<EOF
kubeProxyReplacement: true
k8sServiceHost: "${OPS_IP}"
k8sServicePort: 6443
ipam:
  mode: cluster-pool
  operator:
    clusterPoolIPv4PodCIDRList:
      - "${POD_CIDR}"
operator:
  replicas: 2
gatewayAPI:
  enabled: true
  hostNetwork:
    enabled: true
    nodes:
      matchLabels:
        node-role.kubernetes.io/worker: "true"
hubble:
  enabled: true
  relay:
    enabled: true
  ui:
    enabled: true
EOF

helm upgrade --install cilium cilium/cilium \
  --version "$CILIUM_VER" \
  --namespace kube-system \
  --values /tmp/macprod-cilium-values.yaml \
  --wait --timeout 10m

echo "[bootstrap] Waiting for all Kubernetes nodes to report Ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=5m

echo "[bootstrap] Patching CoreDNS hosts block for *.macprod.internal -> ${OPS_IP}..."
kubectl -n kube-system get configmap coredns -o json > /tmp/macprod-coredns.json
python3 - /tmp/macprod-coredns.json "$OPS_IP" <<'PY' > /tmp/macprod-coredns-patched.json
import sys, json, re
cm = json.load(open(sys.argv[1]))
ops_ip = sys.argv[2]
corefile = cm["data"]["Corefile"]
marker_begin = "# BEGIN MACPROD HOSTS"
marker_end = "# END MACPROD HOSTS"
block = f"""    {marker_begin}
    hosts {{
       {ops_ip} api.macprod.internal ops.macprod.internal gitea.macprod.internal zot.macprod.internal s3.macprod.internal vault.macprod.internal grafana.macprod.internal argocd.macprod.internal order.macprod.internal hubble.macprod.internal
       fallthrough
    }}
    {marker_end}"""
pattern = re.compile(r'\s*# BEGIN MACPROD HOSTS.*?# END MACPROD HOSTS', re.S)
corefile = pattern.sub('', corefile)
corefile = corefile.replace("    kubernetes cluster.local", block + "\n    kubernetes cluster.local", 1)
cm["data"]["Corefile"] = corefile
print(json.dumps(cm))
PY
kubectl apply -f /tmp/macprod-coredns-patched.json
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=3m

echo "[bootstrap] Installing local-path-provisioner (${LPP_VER})..."
kubectl apply -f "https://raw.githubusercontent.com/rancher/local-path-provisioner/${LPP_VER}/deploy/local-path-storage.yaml"
kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}' >/dev/null
kubectl -n local-path-storage patch configmap local-path-config --type merge \
  -p '{"data":{"config.json":"{\n  \"nodePathMap\": [\n    {\n      \"node\": \"DEFAULT_PATH_FOR_NON_LISTED_NODES\",\n      \"paths\": [\"/opt/local-path-provisioner\"]\n    }\n  ]\n}\n"}}'
kubectl -n local-path-storage rollout restart deployment/local-path-provisioner
kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=3m

echo "[bootstrap] Creating Shared Cilium Gateway (HTTP :30080 on worker hostNetwork)..."
kubectl apply -f "$SCRIPT_DIR/cilium-gateway.yaml"

echo "[bootstrap] Installing ArgoCD (${ARGOCD_VER})..."
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
cat >/tmp/macprod-argocd-values.yaml <<EOF
configs:
  params:
    server.insecure: true
  cm:
    timeout.reconciliation: 30s
server:
  replicas: 1
controller:
  resources:
    requests: { cpu: 100m, memory: 256Mi }
    limits: { memory: 1Gi }
repoServer:
  resources:
    requests: { cpu: 50m, memory: 128Mi }
    limits: { memory: 512Mi }
dex:
  enabled: false
EOF

helm upgrade --install argocd argo/argo-cd \
  --version "$ARGOCD_VER" \
  --namespace argocd \
  --values /tmp/macprod-argocd-values.yaml \
  --wait --timeout 10m

echo "[bootstrap] Installing Argo Rollouts (${ROLLOUTS_VER}) with Gateway API plugin (${GW_PLUGIN_VER})..."
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
cat >/tmp/macprod-rollouts-values.yaml <<EOF
controller:
  trafficRouterPlugins:
    - name: "argoproj-labs/gatewayAPI"
      location: "http://s3.macprod.internal:8888/assets/gatewayapi-plugin-linux-arm64"
dashboard:
  enabled: true
EOF

helm upgrade --install argo-rollouts argo/argo-rollouts \
  --version "$ROLLOUTS_VER" \
  --namespace argo-rollouts \
  --values /tmp/macprod-rollouts-values.yaml \
  --wait --timeout 10m

echo "[bootstrap] Day-1 Core Bootstrap complete."
