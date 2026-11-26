#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OPS_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-ops.ip")"
WK1_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-wk-1.ip")"
CP1_IP="$(cat "$ROOT_DIR/.runtime/vm-ips/macprod-cp-1.ip")"
AUTO_KEY="$HOME/.ssh/macprod_ed25519"
TMP_KEY="/tmp/macprod-ephemeral-ca-demo"
SSH_COMMON="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -o LogLevel=ERROR"

cleanup() {
  rm -f "$TMP_KEY" "${TMP_KEY}.pub" "${TMP_KEY}-cert.pub"
}
trap cleanup EXIT

echo "=== [Demo 6] Vault SSH CA Short-Lived Certificate & Zero-Trust SSH ==="

echo "[1/4] Generating unregistered ephemeral ed25519 keypair (NOT in VM authorized_keys)..."
rm -f "$TMP_KEY" "${TMP_KEY}.pub" "${TMP_KEY}-cert.pub"
ssh-keygen -t ed25519 -f "$TMP_KEY" -N "" -C "ephemeral-auditor@macprod" >/dev/null
chmod 600 "$TMP_KEY"

echo "[2/4] Verifying unregistered key and password auth are REJECTED on macprod-wk-1 ($WK1_IP)..."
if ssh -i "$TMP_KEY" $SSH_COMMON "admin@${WK1_IP}" "hostname" >/dev/null 2>&1; then
  echo "ERROR: Unregistered key unexpectedly succeeded!" >&2
  exit 1
fi
PASS_MODE="$(ssh -i "$AUTO_KEY" $SSH_COMMON "admin@${WK1_IP}" "sudo sshd -T | awk '/^passwordauthentication/{print \$2}'")"
echo "  -> Unsigned ephemeral key rejected cleanly; macprod-wk-1 passwordauthentication=${PASS_MODE}"
if [[ "$PASS_MODE" != "no" ]]; then
  echo "ERROR: Expected PasswordAuthentication=no, got ${PASS_MODE}" >&2
  exit 1
fi

echo "[3/4] Requesting 5-minute signed SSH certificate from Vault (ssh-client-signer/sign/macprod-admin)..."
ROOT_TOK="$(ssh -i "$AUTO_KEY" $SSH_COMMON "admin@${OPS_IP}" "sudo jq -r '.root_token' /opt/macprod/vault/init.json")"
SCOPED_TOK="$(curl -fsS -X POST \
  -H "X-Vault-Token: $ROOT_TOK" \
  -H "Content-Type: application/json" \
  -d '{"policies":["ssh-client-sign"],"ttl":"10m","display_name":"demo-auditor"}' \
  "http://${OPS_IP}:8200/v1/auth/token/create" | jq -r '.auth.client_token')"

PUB_CONTENT="$(cat "${TMP_KEY}.pub")"
PAYLOAD="$(jq -nc --arg pk "$PUB_CONTENT" '{public_key: $pk, valid_principals: "admin", ttl: "5m"}')"
SIGNED_CERT="$(curl -fsS -X POST \
  -H "X-Vault-Token: $SCOPED_TOK" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "http://${OPS_IP}:8200/v1/ssh-client-signer/sign/macprod-admin" | jq -r '.data.signed_key')"

printf "%s\n" "$SIGNED_CERT" >"${TMP_KEY}-cert.pub"
chmod 600 "${TMP_KEY}-cert.pub"
ssh-keygen -Lf "${TMP_KEY}-cert.pub" | grep -E "Type:|Signing CA:|Key ID:|Valid:"
ssh-keygen -Lf "${TMP_KEY}-cert.pub" | grep -A1 "Principals:"

echo "[4/4] Logging into macprod-wk-1, macprod-cp-1, and macprod-ops using ONLY the signed 5m cert..."
for target in "macprod-wk-1:${WK1_IP}" "macprod-cp-1:${CP1_IP}" "macprod-ops:${OPS_IP}"; do
  name="${target%%:*}"
  ip="${target##*:}"
  out="$(ssh -i "$TMP_KEY" -o "CertificateFile=${TMP_KEY}-cert.pub" $SSH_COMMON "admin@${ip}" "hostname && whoami")"
  echo "  -> $name ($ip): $(echo "$out" | tr '\n' ' ')"
done

echo "[Demo 6] Completed cleanly: ephemeral key accepted strictly via Vault SSH CA cert."
