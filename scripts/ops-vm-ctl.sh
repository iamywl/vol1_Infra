#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
IP_DIR="$RUNTIME_DIR/vm-ips"
LOG_DIR="$RUNTIME_DIR/logs"

mkdir -p "$IP_DIR" "$LOG_DIR"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5"

vm_names() {
  python3 - "$PROJECT_ROOT/infra/config/cluster.yaml" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
for n in cfg["nodes"]:
    print(n["name"])
PY
}

vm_is_running() {
  local vm="$1"
  tart list 2>/dev/null | awk -v name="$vm" '$1=="local" && $2==name {print $NF}' | grep -qx "running"
}

start_vm() {
  local vm="$1"
  if ! vm_is_running "$vm"; then
    echo "[vm-ctl] Starting $vm..."
    nohup tart run "$vm" --no-graphics --net-softnet-allow=0.0.0.0/0 \
      </dev/null >"$LOG_DIR/${vm}.log" 2>&1 &
  fi
}

wait_ip() {
  local vm="$1"
  local ip=""
  for _ in $(seq 1 60); do
    ip="$(tart ip "$vm" 2>/dev/null || true)"
    if [[ -n "$ip" ]]; then
      echo -n "$ip" >"$IP_DIR/${vm}.ip"
      echo "$ip"
      return 0
    fi
    sleep 2
  done
  echo "[vm-ctl] ERROR: Timeout waiting for IP on $vm" >&2
  return 1
}

wait_ssh() {
  local vm="$1"
  local ip="$2"
  local ssh_user ssh_key
  read -r ssh_user ssh_key < <(python3 - "$PROJECT_ROOT/infra/config/cluster.yaml" <<'PY'
import os, sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
print(cfg["ssh"]["user"], os.path.expanduser(cfg["ssh"]["private_key_path"]))
PY
)
  for _ in $(seq 1 60); do
    if [[ -f "$ssh_key" ]]; then
      if ssh -i "$ssh_key" $SSH_OPTS -o BatchMode=yes "${ssh_user}@${ip}" "true" >/dev/null 2>&1; then
        return 0
      fi
    else
      if python3 - "$ip" <<'PY' >/dev/null 2>&1
import socket, sys
with socket.create_connection((sys.argv[1], 22), timeout=2):
    pass
PY
      then
        return 0
      fi
    fi
    sleep 2
  done
  echo "[vm-ctl] ERROR: Timeout waiting for SSH on $vm ($ip)" >&2
  return 1
}

ensure_vm() {
  local vm="$1"
  local ssh_user="$2"
  local ssh_pass="$3"
  local raw_key_path="$4"
  local key_path="${raw_key_path/#\~/$HOME}"
  local pub_path="${key_path}.pub"

  start_vm "$vm"
  local ip
  ip="$(wait_ip "$vm")"
  echo "[vm-ctl] $vm -> IP $ip"

  local ready=0
  for _ in $(seq 1 45); do
    if ssh -i "$key_path" $SSH_OPTS -o BatchMode=yes "${ssh_user}@${ip}" "echo ok" >/dev/null 2>&1; then
      ready=1
      break
    fi
    if command -v sshpass >/dev/null 2>&1 && \
       sshpass -p "$ssh_pass" ssh $SSH_OPTS "${ssh_user}@${ip}" "echo ok" >/dev/null 2>&1; then
      local pub
      pub="$(cat "$pub_path")"
      sshpass -p "$ssh_pass" ssh $SSH_OPTS "${ssh_user}@${ip}" \
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
      ready=1
      break
    fi
    sleep 2
  done

  if [[ "$ready" -ne 1 ]]; then
    echo "[vm-ctl] ERROR: SSH did not become ready on $vm ($ip)" >&2
    return 1
  fi
}

cmd="${1:-help}"
shift || true

SSH_CERT_DIR="$RUNTIME_DIR/ssh"
USER_SSH_KEY="$HOME/.ssh/macprod_user_ed25519"
USER_SSH_CERT="${USER_SSH_KEY}-cert.pub"
VAULT_SSH_TOKEN_FILE="$RUNTIME_DIR/vault-ssh-token"

ensure_vault_ssh_token() {
  local ops_ip="$1"
  local tok=""
  if [[ -s "$VAULT_SSH_TOKEN_FILE" ]]; then
    tok="$(tr -d '\n\r ' < "$VAULT_SSH_TOKEN_FILE")"
    if curl -fsS -H "X-Vault-Token: $tok" "http://${ops_ip}:8200/v1/auth/token/lookup-self" >/dev/null 2>&1; then
      echo "$tok"
      return 0
    fi
  fi

  local auto_key="$HOME/.ssh/macprod_ed25519"
  local root_tok
  root_tok="$(ssh -i "$auto_key" $SSH_OPTS -o BatchMode=yes "admin@${ops_ip}" \
    "sudo jq -r '.root_token' /opt/macprod/vault/init.json")"
  tok="$(curl -fsS -X POST \
    -H "X-Vault-Token: $root_tok" \
    -H "Content-Type: application/json" \
    -d "{\"policies\":[\"ssh-client-sign\"],\"ttl\":\"24h\",\"display_name\":\"${USER:-engineer}\"}" \
    "http://${ops_ip}:8200/v1/auth/token/create" | jq -r '.auth.client_token')"
  if [[ -z "$tok" || "$tok" == "null" ]]; then
    echo "[vm-ctl] ERROR: Failed to create scoped ssh-client-sign token from Vault" >&2
    return 1
  fi
  umask 077
  printf "%s" "$tok" >"$VAULT_SSH_TOKEN_FILE"
  echo "$tok"
}

write_ssh_config() {
  mkdir -p "$SSH_CERT_DIR"
  chmod 700 "$SSH_CERT_DIR"
  local cfg="$SSH_CERT_DIR/config"
  local v_name ip_file ip
  : >"$cfg"
  chmod 600 "$cfg"
  while IFS= read -r v_name; do
    ip_file="$IP_DIR/${v_name}.ip"
    ip=""
    if [[ -s "$ip_file" ]]; then
      ip="$(tr -d '\n\r ' < "$ip_file")"
    elif vm_is_running "$v_name"; then
      ip="$(wait_ip "$v_name")"
    fi
    [[ -n "$ip" ]] || continue
    cat >>"$cfg" <<EOF
Host $v_name
  HostName $ip
  User admin
  IdentityFile $USER_SSH_KEY
  CertificateFile $USER_SSH_CERT
  IdentitiesOnly yes
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR

EOF
  done < <(vm_names)
  echo "$cfg"
}

issue_ssh_cert() {
  local ttl="${1:-1h}"
  local ops_ip
  ops_ip="$(cat "$IP_DIR/macprod-ops.ip" 2>/dev/null || wait_ip macprod-ops)"

  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  if [[ ! -f "$USER_SSH_KEY" ]]; then
    ssh-keygen -t ed25519 -f "$USER_SSH_KEY" -N "" -C "${USER:-engineer}@macprod-ca" >/dev/null
    chmod 600 "$USER_SSH_KEY"
    chmod 644 "${USER_SSH_KEY}.pub"
  fi

  local tok pub payload signed_key
  tok="$(ensure_vault_ssh_token "$ops_ip")"
  pub="$(cat "${USER_SSH_KEY}.pub")"
  payload="$(jq -nc --arg pk "$pub" --arg ttl "$ttl" '{public_key: $pk, valid_principals: "admin", ttl: $ttl}')"
  signed_key="$(curl -fsS -X POST \
    -H "X-Vault-Token: $tok" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "http://${ops_ip}:8200/v1/ssh-client-signer/sign/macprod-admin" | jq -r '.data.signed_key // empty')"
  if [[ -z "$signed_key" ]]; then
    echo "[vm-ctl] ERROR: Vault did not return signed SSH certificate" >&2
    return 1
  fi
  umask 077
  printf "%s\n" "$signed_key" >"$USER_SSH_CERT"
  chmod 600 "$USER_SSH_CERT"

  local cfg
  cfg="$(write_ssh_config)"
  echo "[ssh-ca] Issued short-lived Vault SSH certificate -> $USER_SSH_CERT"
  ssh-keygen -Lf "$USER_SSH_CERT" | grep -E "Type:|Public key:|Signing CA:|Key ID:|Valid:"
  ssh-keygen -Lf "$USER_SSH_CERT" | grep -A1 "Principals:"
  echo "[ssh-ca] SSH config updated -> $cfg (use: ssh -F $cfg <vm>)"
}

cert_needs_refresh() {
  [[ ! -s "$USER_SSH_CERT" ]] && return 0
  python3 - "$USER_SSH_CERT" <<'PY'
import datetime, re, subprocess, sys
out = subprocess.check_output(["ssh-keygen", "-Lf", sys.argv[1]], text=True)
m = re.search(r"Valid:\s+from\s+\S+\s+to\s+(\S+)", out)
if not m:
    sys.exit(0)
end = datetime.datetime.fromisoformat(m.group(1))
now = datetime.datetime.now()
sys.exit(0 if (end - now).total_seconds() < 60 else 1)
PY
}

case "$cmd" in
  ensure-vm)
    ensure_vm "$@"
    ;;
  start-all)
    while IFS= read -r vm; do
      start_vm "$vm"
    done < <(vm_names)
    while IFS= read -r vm; do
      ip="$(wait_ip "$vm")"
      wait_ssh "$vm" "$ip"
      echo "$vm -> $ip (ssh ready)"
    done < <(vm_names)
    ;;
  stop-all)
    # Stop worker & control-plane VMs first so cluster workloads stop writing S3/Zot/Gitea
    while IFS= read -r vm; do
      if [[ "$vm" != "macprod-ops" ]] && vm_is_running "$vm"; then
        echo "[vm-ctl] Stopping $vm..."
        tart stop "$vm" || true
      fi
    done < <(vm_names)
    if vm_is_running "macprod-ops"; then
      ops_ip="$(tart ip macprod-ops 2>/dev/null || true)"
      if [[ -n "$ops_ip" ]] && [[ -f "$HOME/.ssh/macprod_ed25519" ]]; then
        echo "[vm-ctl] Gracefully flushing macprod-ops containers before VM stop..."
        ssh -i "$HOME/.ssh/macprod_ed25519" $SSH_OPTS -o BatchMode=yes "admin@${ops_ip}" \
          "sudo docker compose -f /opt/macprod/docker-compose.yml stop -t 25 >/dev/null 2>&1 || true" || true
      fi
      echo "[vm-ctl] Stopping macprod-ops..."
      tart stop macprod-ops || true
    fi
    ;;
  status)
    printf "%-16s %-10s %-16s\n" "VM" "STATE" "IP"
    while IFS= read -r vm; do
      state="$(tart list 2>/dev/null | awk -v name="$vm" '$1=="local" && $2==name {print $NF}')"
      state="${state:-missing}"
      ip="-"
      if [[ "$state" == "running" ]]; then
        ip="$(tart ip "$vm" 2>/dev/null || echo pending)"
      fi
      printf "%-16s %-10s %-16s\n" "$vm" "$state" "$ip"
    done < <(vm_names)
    ;;
  sync-ips)
    while IFS= read -r vm; do
      if vm_is_running "$vm"; then
        ip="$(wait_ip "$vm")"
        echo "$vm -> $ip"
      fi
    done < <(vm_names)
    ;;
  doctor)
    echo "=== Mac Prod-in-a-Mac Prerequisite Check ==="
    echo "CPU:        $(sysctl -n machdep.cpu.brand_string) ($(sysctl -n hw.ncpu) cores)"
    echo "RAM:        $(( $(sysctl -n hw.memsize) / 1073741824 )) GB (48 GB allocated for 7 VMs)"
    echo "Disk avail: $(df -h / | awk 'NR==2{print $4}')"
    echo "macOS:      $(sw_vers -productVersion)"
    missing=0
    for c in tart terraform ansible helm kubectl sshpass jq python3 git curl openssl; do
      if command -v "$c" >/dev/null 2>&1; then
        printf "  [OK]      %-10s %s\n" "$c" "$(command -v "$c")"
      else
        printf "  [MISSING] %-10s (install via brew)\n" "$c"
        missing=1
      fi
    done
    if python3 -c "import yaml" >/dev/null 2>&1; then
      echo "  [OK]      pyyaml"
    else
      echo "  [MISSING] pyyaml (pip3 install pyyaml)"
      missing=1
    fi
    if command -v trivy >/dev/null 2>&1; then
      echo "  [OK]      trivy      $(command -v trivy)"
    fi
    if [[ "$missing" -ne 0 ]]; then
      exit 1
    fi
    echo "All required prerequisites passed."
    ;;
  ssh-cert)
    issue_ssh_cert "${1:-1h}"
    ;;
  ssh-config)
    cfg="$(write_ssh_config)"
    echo "[ssh-ca] Wrote $cfg"
    ;;
  ssh)
    vm="${1:-}"
    if [[ -z "$vm" ]]; then
      echo "Usage: $0 ssh <vm-name> [command...]" >&2
      exit 1
    fi
    shift
    if cert_needs_refresh; then
      issue_ssh_cert "1h"
    else
      write_ssh_config >/dev/null
    fi
    exec ssh -F "$SSH_CERT_DIR/config" "$vm" "$@"
    ;;
  *)
    echo "Usage: $0 {doctor|ensure-vm <vm> <user> <pass> <key>|start-all|stop-all|status|sync-ips|ssh-cert [ttl]|ssh-config|ssh <vm> [cmd...]}"
    exit 1
    ;;
esac
