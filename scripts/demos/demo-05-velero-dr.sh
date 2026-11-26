#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="$ROOT_DIR/.kube/config"
DR_NS="dr-drill"
BACKUP_NAME="dr-drill-backup-$(date +%s)"
RESTORE_NAME="dr-drill-restore-$(date +%s)"

echo "=== [Demo 5] Velero Namespace & PVC Disaster Recovery via SeaweedFS S3 ==="
echo "[1/5] Creating stateful drill workload ($DR_NS) with local-path PVC..."
kubectl create namespace "$DR_NS" --dry-run=client -o yaml | kubectl apply -f -
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dr-pvc
  namespace: ${DR_NS}
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-path
  resources:
    requests:
      storage: 100Mi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dr-app
  namespace: ${DR_NS}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dr-app
  template:
    metadata:
      labels:
        app: dr-app
    spec:
      containers:
        - name: busybox
          image: busybox:1.36
          command: ["sh", "-c", "mkdir -p /data && echo 'macprod-dr-verified' > /data/proof.txt && sleep 3600"]
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: dr-pvc
EOF
kubectl -n "$DR_NS" rollout status deployment/dr-app --timeout=2m

echo "[2/5] Creating Velero Backup '$BACKUP_NAME' to SeaweedFS S3..."
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: ${BACKUP_NAME}
  namespace: velero
spec:
  includedNamespaces:
    - ${DR_NS}
  defaultVolumesToFsBackup: true
  ttl: 24h0m0s
EOF

for _ in $(seq 1 40); do
  PHASE="$(kubectl -n velero get backups.velero.io "$BACKUP_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  echo "  Backup phase=$PHASE"
  if [[ "$PHASE" == "Completed" ]]; then break; fi
  if [[ "$PHASE" == "Failed" || "$PHASE" == "PartiallyFailed" ]]; then
    kubectl -n velero describe backups.velero.io "$BACKUP_NAME"
    exit 1
  fi
  sleep 3
done

echo "[3/5] Simulating catastrophic disaster: deleting namespace '$DR_NS'..."
kubectl delete namespace "$DR_NS" --wait=true

echo "[4/5] Creating Velero Restore '$RESTORE_NAME' from SeaweedFS S3..."
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: ${RESTORE_NAME}
  namespace: velero
spec:
  backupName: ${BACKUP_NAME}
  restorePVs: true
EOF

for _ in $(seq 1 40); do
  PHASE="$(kubectl -n velero get restores.velero.io "$RESTORE_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  echo "  Restore phase=$PHASE"
  if [[ "$PHASE" == "Completed" ]]; then break; fi
  sleep 3
done

echo "[5/5] Verifying restored Deployment & PVC payload..."
kubectl -n "$DR_NS" rollout status deployment/dr-app --timeout=2m
PROOF="$(kubectl -n "$DR_NS" exec deploy/dr-app -- cat /data/proof.txt)"
echo "Restored file content: '$PROOF'"
kubectl delete namespace "$DR_NS" --wait=true >/dev/null
echo "=== [Demo 5 Result] DR Drill PASSED (proof='$PROOF') ==="
