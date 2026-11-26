#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"
OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"

echo "=== [Demo 3] CloudNativePG 3-Node HA Primary Failover & S3 Backup ==="
echo "[1/5] Initial CNPG Cluster Pods & Roles:"
kubectl -n apps get pods -l cnpg.io/cluster=order-db -L cnpg.io/instanceRole -o wide

PRIMARY_POD="$(kubectl -n apps get pods -l cnpg.io/cluster=order-db,cnpg.io/instanceRole=primary -o jsonpath='{.items[0].metadata.name}')"
echo "Current Primary Pod: $PRIMARY_POD"

echo "[2/5] Writing sentinel row BEFORE failover..."
SENTINEL="failover-proof-$(date +%s)"
curl -fsS -X POST -H "Host: order.macprod.internal" -H "Content-Type: application/json" \
  -d "{\"item\":\"${SENTINEL}\",\"quantity\":42}" \
  "http://${OPS_IP}/api/v1/orders" && echo ""

echo "[3/5] Force-deleting Primary Pod '$PRIMARY_POD' to trigger automatic CNPG promotion..."
START_TS="$(date +%s)"
kubectl -n apps delete pod "$PRIMARY_POD" --grace-period=0 --force

NEW_PRIMARY=""
for _ in $(seq 1 60); do
  CAND="$(kubectl -n apps get pods -l cnpg.io/cluster=order-db,cnpg.io/instanceRole=primary -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  READY="$(kubectl -n apps get pod "$CAND" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || true)"
  if [[ -n "$CAND" && "$CAND" != "$PRIMARY_POD" && "$READY" == "true" ]]; then
    NEW_PRIMARY="$CAND"
    break
  fi
  sleep 1
done
END_TS="$(date +%s)"
echo "[4/5] Promoted New Primary: ${NEW_PRIMARY:-UNKNOWN} (RTO elapsed: $((END_TS - START_TS))s)"

echo "[5/5] Verifying sentinel data survived failover & triggering on-demand S3 Backup..."
for _ in $(seq 1 15); do
  if curl -fsS -H "Host: order.macprod.internal" "http://${OPS_IP}/api/v1/orders" | grep -q "$SENTINEL"; then
    echo "SUCCESS: Sentinel '$SENTINEL' readable from promoted Primary!"
    break
  fi
  sleep 2
done

cat <<EOF | kubectl apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: order-db-manual-$(date +%H%M%S)
  namespace: apps
spec:
  method: barmanObjectStore
  cluster:
    name: order-db
EOF
kubectl -n apps get backups.postgresql.cnpg.io
