#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"
OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"
GITEA_URL="http://macprod:MacprodGitOps2026!@${OPS_IP}:3000/macprod/gitops.git"
WORKDIR="/tmp/macprod-canary-demo-repo"

echo "=== [Demo 2] Argo Rollouts + Prometheus Error-Rate Auto-Rollback (GitOps Flow) ==="
echo "[1/6] Checking current baseline order-service (v1.0.0):"
curl -fsS -H "Host: order.macprod.internal" "http://${OPS_IP}/api/v1/version" && echo ""
kubectl -n apps get rollout order-service

echo "[2/6] Pushing faulty release (v2.0.0-bad, SIMULATE_ERROR_RATE=0.75) to Gitea GitOps repo..."
rm -rf "$WORKDIR"
git clone -q "$GITEA_URL" "$WORKDIR"
pushd "$WORKDIR" >/dev/null
git config user.name "macprod-demo"
git config user.email "devops@macprod.internal"
python3 - <<'PY'
p = "apps/order-service/k8s/base/rollout.yaml"
txt = open(p).read()
txt = txt.replace('value: "v1.0.0"', 'value: "v2.0.0-bad"', 1)
txt = txt.replace('value: "0.0"', 'value: "0.75"', 1)
open(p, "w").write(txt)
PY
git add apps/order-service/k8s/base/rollout.yaml
git commit -q -m "feat(demo): deploy faulty v2.0.0-bad canary (75% 5xx)"
git push -q origin main
popd >/dev/null

echo "[3/6] Triggering ArgoCD sync on order-service..."
kubectl -n argocd annotate application order-service argocd.argoproj.io/refresh=hard --overwrite >/dev/null
for _ in $(seq 1 40); do
  PHASE="$(kubectl -n apps get rollout order-service -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  CANARY_RS="$(kubectl -n apps get pods -l app=order-service -o jsonpath='{.items[*].spec.containers[0].env[?(@.name=="APP_VERSION")].value}' 2>/dev/null || true)"
  if echo "$CANARY_RS" | grep -q "v2.0.0-bad"; then
    echo "Canary pod v2.0.0-bad is running (Rollout phase=$PHASE)."
    break
  fi
  sleep 3
done

echo "[4/6] Driving live HTTP traffic across Stable + Canary pods so Prometheus catches 5xx rate..."
TRAFFIC_LOG="/tmp/macprod-canary-traffic.log"
rm -f "$TRAFFIC_LOG"
(
  for _ in $(seq 1 150); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: order.macprod.internal" "http://${OPS_IP}/api/v1/orders" || echo 000)"
    echo "$code" >>"$TRAFFIC_LOG"
    sleep 0.2
  done
) &
TRAFFIC_PID=$!

echo "[5/6] Waiting for Argo Rollouts AnalysisRun to fail & auto-abort to Degraded (Stable 100%)..."
ABORTED=0
for _ in $(seq 1 40); do
  PHASE="$(kubectl -n apps get rollout order-service -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  MSG="$(kubectl -n apps get rollout order-service -o jsonpath='{.status.message}' 2>/dev/null || true)"
  echo "  Rollout phase=$PHASE ($MSG)"
  if [[ "$PHASE" == "Degraded" ]]; then
    ABORTED=1
    break
  fi
  sleep 5
done
wait "$TRAFFIC_PID" || true

OK=$(grep -c '^200$' "$TRAFFIC_LOG" || true)
ERR=$(grep -cv '^200$' "$TRAFFIC_LOG" || true)
echo "Traffic stats during faulty canary: 200=$OK, non-200=$ERR"
kubectl -n apps get analysisrun
kubectl -n apps get httproute order-service-route -o jsonpath='{.spec.rules[0].backendRefs}'; echo ""

echo "[6/6] Reverting GitOps repo back to clean v1.0.0 (self-heal recovery)..."
pushd "$WORKDIR" >/dev/null
git revert --no-edit HEAD >/dev/null
git push -q origin main
popd >/dev/null
rm -rf "$WORKDIR"
kubectl -n argocd annotate application order-service argocd.argoproj.io/refresh=hard --overwrite >/dev/null
for _ in $(seq 1 30); do
  PHASE="$(kubectl -n apps get rollout order-service -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [[ "$PHASE" == "Healthy" ]]; then break; fi
  sleep 3
done
echo "=== [Demo 2 Result] Canary Aborted=${ABORTED}, Final Rollout Phase=$(kubectl -n apps get rollout order-service -o jsonpath='{.status.phase}') ==="
if [[ "$ABORTED" -ne 1 ]]; then
  echo "ERROR: Canary v2.0.0-bad was not automatically aborted!" >&2
  exit 1
fi
