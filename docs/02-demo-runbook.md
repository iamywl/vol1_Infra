# 02. Demo 실행 가이드 (Runbook)

본 문서는 `Prod-in-a-Mac` 전체 스택을 처음부터 구축(Zero-to-Ready)하고, 데브옵스 핵심 역량 5가지(3-Master HA, GitOps 카나리 자동 롤백, PostgreSQL HA Failover & S3 백업, Vault/Kyverno 보안 통제, Velero DR 및 관측성·부하 검증)를 시연하는 절차를 다룬다.

---

## 0. 사전 준비 및 전체 구축 (`make up`)

```bash
cd /Users/ywlee/sideproejct/INFRA/vol1_Infra

# 전체 일괄 구축 (VM 7대 -> Ops -> 3-Master HA K8s -> Day-1 Cilium/ArgoCD -> S3/Vault/GitOps)
make up

# 전체 상태 확인
make status
```

단계별로 나누어 실행할 수도 있다.
1. `make tf-vms` — Layer-1 Terraform이 7개 Tart VM 생성·부팅 및 SSH 키(`~/.ssh/macprod_ed25519`), Ansible 인벤토리(`infra/ansible/inventories/hosts.ini`) 생성
2. `make ansible-all` — OS 튜닝, `macprod-ops` 외부 스택(`HAProxy`, `SeaweedFS`, `Zot`, `Gitea`, `Vault`, `k6`), `kubeadm v1.32` 3-Master HA 클러스터 구축
3. `make bootstrap` — `Gateway API v1.6.3`, `Cilium 1.20.5`, `CoreDNS` 내부 도메인 패치, `local-path-provisioner`, `ArgoCD`, `Argo Rollouts` 설치
4. `make platform` — Layer-2 Terraform(`SeaweedFS S3` 백엔드 + Vault + 네임스페이스 거버넌스), `order-service:v1.0.0` ARM64 빌드/Zot 푸시/Trivy 스캔, Gitea GitOps 푸시 및 `macprod-root` 적용

---

## 1. 엔드포인트 접속 확인 (로컬 Mac 호스트 기준)

`macprod-ops` IP를 조회해 `Host` 헤더와 함께 호출하거나, 필요 시 로컬 `/etc/hosts`에 매핑해 브라우저로 열 수 있다.

```bash
OPS_IP=$(cat .runtime/vm-ips/macprod-ops.ip)

# Order Service API (HAProxy :80 -> Cilium Envoy :30080 -> order-service -> CNPG PostgreSQL)
curl -H "Host: order.macprod.internal" "http://${OPS_IP}/api/v1/version"
curl -X POST -H "Host: order.macprod.internal" -H "Content-Type: application/json" \
  -d '{"item":"demo-item","quantity":1}' "http://${OPS_IP}/api/v1/orders"

# ArgoCD / Grafana / Hubble UI
curl -I -H "Host: argocd.macprod.internal" "http://${OPS_IP}/"
curl -I -H "Host: grafana.macprod.internal" "http://${OPS_IP}/login"
curl -I -H "Host: hubble.macprod.internal" "http://${OPS_IP}/"

# ArgoCD 초기 admin 비밀번호 조회
KUBECONFIG=.kube/config kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo ""
```

브라우저에서 도메인으로 바로 접속하려면 `/etc/hosts`에 아래 한 줄을 임시 추가한다.
```text
<OPS_IP> order.macprod.internal argocd.macprod.internal grafana.macprod.internal hubble.macprod.internal gitea.macprod.internal vault.macprod.internal zot.macprod.internal s3.macprod.internal
```
- **Gitea**: `http://<OPS_IP>:3000` (`macprod` / `MacprodGitOps2026!`)
- **Zot Registry UI**: `http://<OPS_IP>:5000`
- **Vault UI**: `http://<OPS_IP>:8200` (`root_token`은 `macprod-ops:/opt/macprod/vault/init.json` 참고)
- **HAProxy Stats**: `http://<OPS_IP>:8404/stats`
- **Grafana**: `http://grafana.macprod.internal` (`admin` / `admin`)

---

## 2. 5대 핵심 데모 시나리오

### Demo 1 — 3-Master HA Control Plane 장애 무중단 & `etcd` S3 백업 (`make demo-ha`)
- **검증 내용**: `macprod-cp-2` VM을 강제 종료(`tart stop`)하는 동안 `HAProxy`의 1~2초 헬스체크 전환과 `2/3 etcd` Raft 쿼럼 유지로 Kubernetes API 쓰기(`ConfigMap` 생성/삭제)가 정상 동작함을 확인하고, `etcd` 스냅샷(`~62 MB`)을 `SeaweedFS S3`에 백업한 뒤 노드를 재기동해 복귀시킨다.
- **실행**:
  ```bash
  make demo-ha
  ```
- **확인 포인트**: `/healthz` 40회 연속 프로브 중 장애 감지 1~2초 구간 외 `200 OK` 유지, `s3://terraform-state/etcd-backups/...` 업로드 성공, `macprod-cp-2` `Ready` 복귀.

### Demo 2 — Argo Rollouts + Gateway API + Prometheus 5xx 자동 롤백 (`make demo-canary`)
- **검증 내용**: `Gitea`의 `gitops` 저장소에 75% HTTP 500 오류를 내는 `v2.0.0-bad` 커밋을 푸시하면 `ArgoCD`가 동기화하고, `Argo Rollouts`가 `Cilium Gateway API HTTPRoute` 가중치를 25%로 분할한 뒤 `AnalysisTemplate`(`non-5xx-ratio >= 0.90`)이 Prometheus 5xx 급증을 탐지해 자동으로 `RolloutAborted`·트래픽 100% 원복(`weight: 100/0`)을 수행한다. 이후 Git Revert 커밋으로 `Healthy` 상태까지 자동 복구한다.
- **실행**:
  ```bash
  make demo-canary
  ```
- **확인 포인트**: `Metric "non-5xx-ratio" assessed Failed`, `HTTPRoute` 가중치 `100 / 0` 복원, 최종 `Rollout` `Healthy`.

### Demo 3 — CloudNativePG 3-노드 PostgreSQL HA Failover & S3 백업 (`make demo-db`)
- **검증 내용**: 쓰기 요청으로 센티넬 레코드를 적재한 뒤 현재 Primary Pod(`order-db-x`)를 `--force` 삭제한다. `CloudNativePG`가 Standby 중 1대를 자동 Primary로 승격시키며, 데이터 손실 없이 동일 API 조회가 가능함과 `SeaweedFS S3`(`s3://cnpg-backups/`) 온디맨드 백업 완료를 검증한다.
- **실행**:
  ```bash
  make demo-db
  ```
- **확인 포인트**: 승격 RTO(약 `24s` 내외), 센티넬 행 보존 확인, `backups.postgresql.cnpg.io` `completed`.

### Demo 4 — Vault → ESO 동적 시크릿 회전 & Kyverno CEL 정책 차단 (`make demo-security`)
- **검증 내용**:
  1. `Vault`의 `secret/apps/order-service` 값을 변경한 뒤 `ExternalSecret` `force-sync`로 Kubernetes `Secret`이 즉시 갱신됨을 확인하고 원복한다.
  2. `Kyverno v1.20` CEL `ValidatingPolicy`가 `apps` 네임스페이스에서 `:latest` 태그 Pod와 `allowPrivilegeEscalation=false` 미설정 Pod 생성을 Admission 단계에서 즉시 거부함을 확인한다.
- **실행**:
  ```bash
  make demo-security
  ```

### Demo 5 — Velero 네임스페이스 · PVC 재해 복구 (`make demo-velero`)
- **검증 내용**: `local-path` PVC에 증명 파일(`/data/proof.txt`)을 기록한 테스트 네임스페이스(`dr-drill`)를 `Velero` + `Kopia` 파일시스템 백업으로 `SeaweedFS S3`(`s3://velero-backups/`)에 저장한 뒤 네임스페이스를 완전히 삭제한다. 이어서 `Restore`를 실행해 파드와 PVC 데이터가 복구됨을 검증한다.
- **실행**:
  ```bash
  make demo-velero
  ```
- **주의**: 클러스터에 `CloudNativePG`와 `Velero`가 모두 `Backup` CRD를 등록하므로 CLI 조회 시 `kubectl -n velero get backups.velero.io`처럼 그룹을 명시해야 한다.

### Demo 6 — Vault SSH CA 단기 인증서 발급 & Zero-Trust VM 접속 (`make demo-ssh`)
- **검증 내용**:
  1. VM `authorized_keys`에 전혀 등록되지 않은 일회용 `ed25519` 키페어를 생성해 접속 시도를 하면 `Permission denied`로 차단되고, 모든 VM이 `PasswordAuthentication no`(`10-macprod-ssh-ca.conf`) 상태임을 검증한다.
  2. Vault의 최소 권한 정책(`ssh-client-sign`) 토큰으로 `/v1/ssh-client-signer/sign/macprod-admin` API에서 `5m` 단기 SSH 인증서를 발급받는다.
  3. 동일 일회용 키 + 서명된 인증서만으로 `macprod-wk-1`, `macprod-cp-1`, `macprod-ops` 접속(`hostname && whoami`)이 즉시 통과함을 확인한다.
- **실행**:
  ```bash
  make demo-ssh

  # 일상 운영자 단기 인증서 발급(기본 TTL 1h) 및 원커맨드 VM 접속
  make ssh-cert
  make ssh VM=macprod-wk-1
  make ssh VM=macprod-cp-1 CMD="sudo crictl ps"
  ```

---

## 3. 부하 테스트 (`k6`) 및 관측성(Metric · Log · Trace) 검증

### `k6` 부하 테스트 실행
```bash
OPS_IP=$(cat .runtime/vm-ips/macprod-ops.ip)
scp -i ~/.ssh/macprod_ed25519 tests/k6/canary-load.js "admin@${OPS_IP}:/tmp/canary-load.js"
ssh -i ~/.ssh/macprod_ed25519 "admin@${OPS_IP}" \
  "BASE_URL=http://127.0.0.1 HOST_HEADER=order.macprod.internal k6 run /tmp/canary-load.js"
```

### Prometheus · Loki · Tempo 수집 확인
```bash
# 별도 터미널 포트포워드 또는 Grafana UI(Explore)에서 확인
KUBECONFIG=.kube/config kubectl -n observability port-forward svc/kps-kube-prometheus-stack-prometheus 19090:9090 &
KUBECONFIG=.kube/config kubectl -n observability port-forward svc/loki 13100:3100 &
KUBECONFIG=.kube/config kubectl -n observability port-forward svc/tempo 13200:3200 &

curl -s 'http://127.0.0.1:19090/api/v1/query?query=sum(http_requests_total{namespace="apps"})'
curl -s 'http://127.0.0.1:13100/loki/api/v1/query_range?query={namespace="apps",container="order-service"}&limit=3'
curl -s 'http://127.0.0.1:13200/api/search?tags=service.name%3Dorder-service&limit=3'
```

---

## 4. 일상 운영: 정지, Mac 재부팅 후 IP 드리프트 복구, 완전 삭제

```bash
# 작업 종료 시 VM 안전 정지 (다른 Tart VM은 건드리지 않음)
make stop

# Mac 재부팅 또는 VM 재기동 후 DHCP IP 변경 시 일괄 복구
make reconcile

# 전체 실습 환경 삭제
make destroy
```
