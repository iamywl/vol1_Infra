#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"
OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"
CP1_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-cp-1.ip")"
SSH_KEY="$(python3 -c 'import os,yaml; c=yaml.safe_load(open("'"$ROOT_DIR"'/infra/config/cluster.yaml")); print(os.path.expanduser(c["ssh"]["private_key_path"]))')"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "=== [Demo 1] 3-Master HA Control Plane Failover & etcd S3 Backup ==="
echo "[1/5] Initial Node & etcd Quorum Status:"
kubectl get nodes
ssh $SSH_OPTS "admin@${CP1_IP}" "sudo crictl exec \$(sudo crictl ps --name '^etcd$' -q | head -n1) etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key member list -w table"

echo "[2/5] Starting continuous API server /healthz probe in background..."
PROBE_LOG="/tmp/macprod-ha-probe.log"
rm -f "$PROBE_LOG"
(
  for _ in $(seq 1 40); do
    code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${OPS_IP}:6443/healthz" || echo 000)"
    echo "$(date +%H:%M:%S) healthz=$code" >>"$PROBE_LOG"
    sleep 1
  done
) &
PROBE_PID=$!

echo "[3/5] Forcing hard shutdown of macprod-cp-2 (simulating control-plane host crash)..."
tart stop macprod-cp-2
sleep 4

echo "[4/5] Testing API writes (ConfigMap create/delete) with 2/3 control planes alive:"
kubectl create configmap ha-quorum-proof --from-literal=state=survives-cp2-loss -n default --dry-run=client -o yaml | kubectl apply -f -
kubectl get configmap ha-quorum-proof -n default
kubectl delete configmap ha-quorum-proof -n default

echo "[5/5] Running etcd snapshot backup & upload to SeaweedFS S3 from macprod-cp-1..."
ssh $SSH_OPTS "admin@${CP1_IP}" "sudo /usr/local/bin/etcd-s3-backup.sh"

echo "Bringing macprod-cp-2 back online..."
nohup tart run macprod-cp-2 --no-graphics --net-softnet-allow=0.0.0.0/0 </dev/null >"$ROOT_DIR/.runtime/logs/macprod-cp-2.log" 2>&1 &
for _ in $(seq 1 45); do
  if kubectl get node macprod-cp-2 --no-headers 2>/dev/null | grep -q " Ready "; then
    break
  fi
  sleep 2
done
wait "$PROBE_PID" || true

OK_CNT=$(grep -c "healthz=200" "$PROBE_LOG" || true)
FAIL_CNT=$(grep -cv "healthz=200" "$PROBE_LOG" || true)
echo "=== [Demo 1 Result] API Probes: 200 OK=${OK_CNT}, Non-200=${FAIL_CNT} ==="
kubectl get nodes
