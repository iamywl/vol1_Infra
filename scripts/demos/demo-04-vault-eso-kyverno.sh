#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"
OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"
SSH_KEY="$(python3 -c 'import os,yaml; c=yaml.safe_load(open("'"$ROOT_DIR"'/infra/config/cluster.yaml")); print(os.path.expanduser(c["ssh"]["private_key_path"]))')"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
VAULT_TOKEN="$(ssh $SSH_OPTS "admin@${OPS_IP}" "sudo jq -r '.root_token' /opt/macprod/vault/init.json")"

echo "=== [Demo 4] Vault -> ESO Dynamic Secret Sync & Kyverno Admission Gate ==="
echo "[1/3] Current API_KEY stored in K8s Secret (synced from Vault):"
kubectl -n apps get secret order-service-env -o jsonpath='{.data.API_KEY}' | base64 -d; echo ""

echo "[2/3] Rotating API_KEY in HashiCorp Vault and forcing ESO sync..."
ssh $SSH_OPTS "admin@${OPS_IP}" "sudo docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=${VAULT_TOKEN} macprod-vault vault kv patch secret/apps/order-service API_KEY=macprod-secret-v2-rotated >/dev/null"
kubectl -n apps annotate externalsecret order-service-env force-sync="$(date +%s)" --overwrite >/dev/null
sleep 4
echo -n "Updated API_KEY in K8s Secret: "
kubectl -n apps get secret order-service-env -o jsonpath='{.data.API_KEY}' | base64 -d; echo ""

# Restore original token cleanly
ssh $SSH_OPTS "admin@${OPS_IP}" "sudo docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=${VAULT_TOKEN} macprod-vault vault kv patch secret/apps/order-service API_KEY=macprod-secret-v1-token >/dev/null"
kubectl -n apps annotate externalsecret order-service-env force-sync="$(date +%s)" --overwrite >/dev/null

echo "[3/3] Testing Kyverno Admission Policies in 'apps' namespace:"
echo "  (a) Attempting Pod with disallowed ':latest' image tag (expected: REJECTED):"
if kubectl -n apps run kyverno-bad-latest --image=nginx:latest --restart=Never --dry-run=server --overrides='{"spec":{"containers":[{"name":"kyverno-bad-latest","image":"nginx:latest","securityContext":{"allowPrivilegeEscalation":false}}]}}' 2>&1; then
  echo "ERROR: latest tag was not blocked!"
  exit 1
else
  echo "  -> BLOCKED cleanly by Kyverno."
fi

echo "  (b) Attempting Pod without allowPrivilegeEscalation=false (expected: REJECTED):"
if kubectl -n apps run kyverno-bad-priv --image=nginx:1.27-alpine --restart=Never --dry-run=server 2>&1; then
  echo "ERROR: non-hardened container was not blocked!"
  exit 1
else
  echo "  -> BLOCKED cleanly by Kyverno."
fi
