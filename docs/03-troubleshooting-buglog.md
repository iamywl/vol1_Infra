# 03. 구현 및 검증 중 발생한 트러블슈팅 & 버그 로그

본 문서는 Option A(`Prod-in-a-Mac`)를 Apple M4 Max 환경에서 실제로 구축하고 5대 데모까지 전수 검증하는 과정에서 **실제 발생한 오류·환경 제약·버전 비호환 13건**과 그 근본 원인, 적용한 해결책, 재발 방지 조치를 기록한다.

---

### Bug #01. MinIO 커뮤니티 바이너리 및 Docker 이미지 배포 중단 (`410 Gone` / `401 Unauthorized`)
- **발생 단계**: 스택 사전 검증
- **관찰 현상**:
  - `HEAD https://dl.min.io/server/minio/release/linux-arm64/minio` → `HTTP Error 410: Gone`
  - `quay.io/minio/minio:latest` / `docker.io/minio/minio` 매니페스트 조회 → `HTTP Error 401: Unauthorized`
  - MinIO 공식 GitHub `README.md` 확인 결과: *"THIS REPOSITORY IS NO LONGER MAINTAINED ... MinIO community edition is now distributed as source code only"* 안내 확인.
- **원인**: 2025~2026년 MinIO가 커뮤니티 사전 빌드 바이너리 및 컨테이너 이미지 배포를 중단했다.
- **해결**: Apache 2.0 라이선스이면서 공식 `linux/arm64` 멀티아키텍처를 제공하는 **SeaweedFS `4.55` (`chrislusf/seaweedfs:4.55`)** 로 교체하고 Terraform S3 백엔드, CNPG Barman, Velero 연동 테스트를 완료했다.

---

### Bug #02. Harbor 공식 레지스트리 이미지의 `linux/amd64` 단일 아키텍처 제한
- **발생 단계**: 스택 사전 검증
- **관찰 현상**: Docker Hub 매니페스트 API로 `goharbor/harbor-core` `v2.11.2`, `v2.12.2`, `v2.13.0`을 조회한 결과 모두 `SINGLE: linux amd64`만 존재했다.
- **원인**: Harbor 공식 릴리즈가 여전히 `linux/arm64`를 공식 배포하지 않아 Apple Silicon Linux VM에서 에뮬레이션 없이 네이티브 실행이 불가하다.
- **해결**: `linux/arm64` + `linux/amd64` 공식 멀티아키텍처와 OCI v1.1·UI·검색 기능을 단일 경량 바이너리로 제공하는 **CNCF Zot `v2.1.2` (`ghcr.io/project-zot/zot:v2.1.2`)** + `Trivy CLI`로 대체했다.

---

### Bug #03. Tart `--net-softnet` 환경에서 비DHCP VIP(L2 ARP) 차단
- **발생 단계**: 가상화 네트워크 설계 검증 (`tart run --help`)
- **관찰 현상**: `--net-softnet` 사용 시 Softnet 유저스페이스 패킷 필터가 게스트 VM 자신의 MAC 주소와 DHCP 할당 IP 이외의 발신 트래픽을 차단한다.
- **원인**: `Keepalived VRRP`나 `MetalLB L2`/`Cilium L2 Announcements`처럼 가상 VIP와 Gratuitous ARP를 사용하는 방식은 Softnet 환경에서 패킷이 드롭된다.
- **해결**: 외부 `macprod-ops` VM의 **HAProxy 3.0**이 클러스터 K8s API(`:6443`)와 워커 Envoy(`:30080`) 앞단 로드밸런서 역할을 수행하고, Cilium은 `gatewayAPI.hostNetwork.enabled=true`로 워커의 실제 DHCP IP에 바인딩하도록 설계했다.

---

### Bug #04. HAProxy 3.0에서 `option httpchk` 인라인 헤더 문법 제거
- **발생 단계**: `02-ops-node.yml` 실행 (`macprod-haproxy` 기동 실패 `Exited (1)`)
- **관찰 현상**:
  ```text
  [ALERT] parsing [/usr/local/etc/haproxy/haproxy.cfg:44] : 'option httpchk' : hiding headers or body at the end of the version string is unsupported. Use 'http-check send' directive instead.
  ```
- **원인**: HAProxy 3.0부터 `option httpchk GET /path HTTP/1.1\r\nHost: ...` 형태의 인라인 `\r\n` 헤더 삽입이 금지되었다.
- **해결**: [haproxy.cfg.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/haproxy.cfg.j2)에서 `option httpchk`와 `http-check send meth GET uri /healthz ver HTTP/1.1 hdr Host healthz.macprod.internal` 지시자로 분리했다.

---

### Bug #05. HAProxy 3.0 비루트 컨테이너 `:80` 포트 바인딩 거부
- **발생 단계**: Bug #04 수정 후 `macprod-haproxy` 재기동 (`Exited (1)`)
- **관찰 현상**:
  ```text
  [ALERT] Binding [/usr/local/etc/haproxy/haproxy.cfg:36] for frontend http_ingress: protocol tcpv4: cannot bind socket (Permission denied) for [0.0.0.0:80].
  ```
- **원인**: `haproxy:3.0-alpine` 공식 이미지는 비루트 `haproxy` 유저로 동작하며, `network_mode: host`에서는 리눅스 커널의 기본 `ip_unprivileged_port_start=1024` 정책 때문에 비루트 프로세스가 `:80` 포트를 열 수 없다.
- **해결**: 컨테이너를 root로 승격하지 않고 최소 권한 원칙을 지키기 위해 `macprod-ops` 호스트의 `/etc/sysctl.d/90-macprod-ops.conf`에 `net.ipv4.ip_unprivileged_port_start = 80`을 적용했다.

---

### Bug #06. HashiCorp Vault `docker-entrypoint.sh`의 `-config` 중복 전달 (`address already in use`)
- **발생 단계**: `02-ops-node.yml`의 `/opt/macprod/scripts/bootstrap-ops.sh` 실행 (`rc: 137`)
- **관찰 현상**: `macprod-vault` 로그에 아래 오류가 반복되며 재시작 루프 진입:
  ```text
  Error parsing listener configuration.
  Error initializing listener of type tcp: listen tcp4 0.0.0.0:8200: bind: address already in use
  ```
- **원인**: 공식 이미지의 `/usr/local/bin/docker-entrypoint.sh`를 직접 추출해 확인한 결과, 첫 번째 인자가 `server`이면 엔트리포인트가 내부적으로 `vault server -config="$VAULT_CONFIG_DIR"`를 자동 추가한다. Compose `command`에 `["server", "-config=/vault/config/vault.hcl"]`을 지정하자 `/vault/config` 디렉터리와 `/vault/config/vault.hcl` 파일이 중복 로드되어 `0.0.0.0:8200` 바인딩을 두 번 시도했다.
- **해결**: [docker-compose.yml.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/docker-compose.yml.j2)의 Vault 명령을 `command: ["server"]`로 수정했다.

---

### Bug #07. SeaweedFS `4.55` 비루트 권한 거부 & `-ip=127.0.0.1` 바인딩 격리
- **발생 단계**: `02-ops-node.yml`의 S3 버킷 초기화(`bootstrap-ops.sh`)
- **관찰 현상**:
  1. 1차 시도 로그: `fail to read /etc/seaweedfs/s3.json : open /etc/seaweedfs/s3.json: permission denied`
  2. 파일 권한 수정 후 2차 시도 에러: `botocore.exceptions.ConnectionClosedError: Connection was closed before we received a valid response from endpoint URL: "http://127.0.0.1:8333/"` (동시에 호스트 `curl`은 빈 응답으로 끊김)
- **원인**:
  1. `chrislusf/seaweedfs:4.55` `/entrypoint.sh`는 `/data`만 `chown`한 뒤 `su-exec seaweed`로 권한을 강등한다. Ansible이 `0600 root:root`로 배포한 `/opt/macprod/config/seaweedfs-s3.json`을 `seaweed` 유저가 읽지 못했다.
  2. `weed server` 실행 시 `-ip=127.0.0.1`만 주면 `-ip.bind` 기본값도 `127.0.0.1`이 되어 컨테이너 내부 루프백에만 바인딩된다. Docker `docker-proxy`가 컨테이너 `eth0:8333`으로 전달한 요청이 즉시 Reset되었다.
- **해결**:
  1. `seaweedfs-s3.json` 권한을 `0644`로 변경.
  2. 실행 인자에 `-ip.bind=0.0.0.0`과 `-s3.allowEmptyFolder` 추가.
  3. `bootstrap-ops.sh.j2` S3 대기 루프가 단순 `curl -s` 성공 여부가 아니라 실제 HTTP 상태 코드(`[234]`) 수신을 검증하도록 수정.

---

### Bug #08. Ansible `shell` 모듈의 `dash` `/bin/sh` 환경에서 `set -o pipefail` 실패
- **발생 단계**: `03-k8s-cluster.yml` (`Install Kubernetes apt repository keyring and source`)
- **관찰 현상**: 전체 6개 K8s 노드에서 `/bin/sh: 1: set: Illegal option -o pipefail` (`rc: 2`)로 중단.
- **원인**: Ubuntu 24.04의 `/bin/sh`는 `dash`이며 Ansible `shell` 모듈은 별도 지정이 없으면 `/bin/sh`를 사용한다. `dash`는 `pipefail` 옵션을 지원하지 않는다.
- **해결**: [ansible.cfg](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/ansible.cfg) `[defaults]`에 `executable = /bin/bash`를 전역 설정해 Ubuntu와 macOS(`localhost`) 양쪽에서 일관되게 `bash`를 사용하도록 통일했다.

---

### Bug #09. Cilium `1.20.5` ↔ Gateway API `v1.6.3` 정합성 & CoreDNS 패치 파이프 `stdin` 충돌
- **발생 단계**: `platform/bootstrap/install-core.sh` 작성·실행
- **관찰 현상**:
  1. Cilium `v1.20.5` `go.mod` 확인 결과 `sigs.k8s.io/gateway-api v1.6.3`을 요구한다(`v1.2.1` 사용 시 스키마 불일치 위험).
  2. CoreDNS 패치 실행 중 `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` 발생.
- **원인**: `kubectl get configmap coredns -o json | python3 - "$OPS_IP" <<'PY'` 구문에서 `<<'PY'` heredoc 리다이렉션이 파이프로 들어오는 표준입력(`stdin`)을 덮어써 `sys.stdin`이 비어버렸다.
- **해결**: Gateway API CRD를 `v1.6.3/experimental-install.yaml`로 맞췄고, CoreDNS JSON을 임시 파일(`/tmp/macprod-coredns.json`)로 저장해 `sys.argv[1]`로 읽도록 수정했다.

---

### Bug #10. `apt-daily-upgrade.service` 백그라운드 실행으로 `systemd-resolved` 재시작 중 `ErrImagePull` 발생
- **발생 단계**: ArgoCD Wave 3 파드 스케줄링 (`velero`, `kps-grafana`, `node-exporter`)
- **관찰 현상**: `macprod-wk-2` 노드에 배치된 복수 파드가 동시에 DNS 조회 거부 오류로 `ErrImagePull`:
  ```text
  lookup quay.io on 127.0.0.53:53: read udp ...->127.0.0.53:53: read: connection refused
  ```
- **원인**: `macprod-wk-2`의 `journalctl` 정밀 분석 결과, 부팅 직후 실행된 `apt-daily-upgrade.service`가 패키지를 자동 업그레이드하면서 `16:17:49`에 `Reexecuting requested from client PID 79426 ('systemctl') (unit apt-daily-upgrade.service)`를 유발했고, 그 여파로 `systemd-resolved`와 `systemd-networkd`가 일시 중지 후 재시작되는 수백 ms 동안 `127.0.0.53:53`이 닫혔다.
- **해결**: [roles/common/tasks/main.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/common/tasks/main.yml)과 실행 중인 전체 7개 VM에서 `apt-daily.timer`, `apt-daily-upgrade.timer`, `unattended-upgrades`를 중지·마스킹해 운영 중 예기치 않은 `systemd` 재실행을 차단했다.

---

### Bug #11. `Loki 7.7.0` Helm Test 의존 검증 오류 & `order-service` Sync Wave CRD 레이스
- **발생 단계**: ArgoCD Wave 3~4 자동 동기화
- **관찰 현상**:
  1. `loki` 애플리케이션 `Unknown`: `Error: execution error at (loki/templates/validate.yaml:6:4): Helm test requires the Loki Canary to be enabled`
  2. `order-service` 애플리케이션 `OutOfSync`: `failed to discover server resources for group version monitoring.coreos.com/v1: the server could not find the requested resource`
- **원인**:
  1. `loki 7.7.0` 차트는 `test.enabled: true`가 기본값이며, `lokiCanary.enabled=false` 시 `test.enabled: false`를 함께 명시하지 않으면 템플릿 렌더링을 거부한다.
  2. ArgoCD App-of-Apps는 하위 `Application`의 내부 파드/CRD 완료를 기다리지 않고 동기화를 시도해 `kube-prometheus-stack`의 `ServiceMonitor` CRD 등록 직전에 `order-service` dry-run이 충돌했다.
- **해결**: [09-loki.yaml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/gitops/apps/09-loki.yaml)에 `test.enabled: false`를 추가했고, [13-order-service.yaml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/gitops/apps/13-order-service.yaml)에 `SkipDryRunOnMissingResource=true`를, 대용량 CRD를 가진 모든 차트 앱에 `ServerSideApply=true`를 적용했다.

---

### Bug #12. `Kyverno v1.20` 레거시 `ClusterPolicy` 실행 제거 · `LimitRanger` 선실행 · `Backup` CRD 단축명 충돌
- **발생 단계**: `platform-configs` 동기화 및 `Demo 4`·`Demo 5` 검증
- **관찰 현상**:
  1. `platform-configs` `Degraded`: `kyverno.io/v1 ClusterPolicy: Kyverno v1.20 removed execution of legacy kyverno.io policy types ... Migrate to ValidatingPolicy (policies.kyverno.io)`
  2. `Demo 4`에서 메모리 limit 없이 Pod를 생성했으나 차단되지 않음 (`LimitRanger` 충돌).
  3. `Demo 5`에서 `kubectl -n velero get backup "$BACKUP_NAME"` 폴링이 120초간 빈 문자열(`Backup phase=`)만 출력했으나, 실제 백업은 2초 만에 완료되어 S3에 저장되어 있었고 복구도 성공했다.
- **원인**:
  1. Kyverno `3.10.0` (`v1.20.0`)이 기존 `ClusterPolicy` 생성·실행을 폐지하고 CEL 기반 `policies.kyverno.io/v1 ValidatingPolicy`만 허용한다. (유사하게 `external-secrets 2.15.0`도 `v1beta1` deprecated 경고가 있어 `external-secrets.io/v1`로 상향했고, `apps` PSS를 `enforce: baseline` + `warn: restricted`로 조정해 CNPG `initdb` Job과의 충돌을 막았다.)
  2. Kubernetes API 서버는 **Mutating Admission(`LimitRanger`)** 을 **Validating Webhook(Kyverno)** 보다 먼저 실행하므로, Terraform이 만든 `apps-default-limits`가 `512Mi` 기본 limit을 먼저 주입해 Kyverno 검증이 통과되었다.
  3. 클러스터에 `backups.postgresql.cnpg.io`와 `backups.velero.io` 두 CRD가 공존해, 그룹을 생략한 `kubectl get backup`이 CNPG 백업 CRD로 해석되었다.
- **해결**:
  1. [kyverno-policies.yaml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/gitops/components/platform-configs/kyverno-policies.yaml)을 `policies.kyverno.io/v1 ValidatingPolicy`(CEL)로 전환하고 `disallow-privilege-escalation` 정책을 추가(`cnpg.io/cluster` 라벨 제외)했다.
  2. 기존 실패 상태의 ArgoCD `operation` 백오프를 제거해 신규 커밋 재동기화를 완료했다.
  3. [demo-05-velero-dr.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/demos/demo-05-velero-dr.sh)에서 `backups.velero.io` / `restores.velero.io` 완전한 리소스명을 사용하도록 수정해 3초 내 상태 전환 확인을 복구했다.

---

### Bug #13. Bash 백그라운드 서브셸 카운터 스코프 손실 & Grafana Distroless 실행 파일 부재
- **발생 단계**: `Demo 2` 1차 실행 및 관측성 API 검증
- **관찰 현상**:
  1. `Demo 2` 종료 요약에서 실제 트래픽과 무관하게 `Traffic stats during faulty canary: 200=0, non-200=0` 출력.
  2. `kubectl -n observability exec deploy/kps-grafana -c grafana -- sh` 실행 시 `exec: "sh": executable file not found in $PATH` 오류.
  3. Mac `zsh` 터미널에서 unquoted `$SSH_OPTS` 전달 시 단어 분할이 일어나지 않아 SSH 옵션 인식 실패.
- **원인**:
  1. `for ... &` 백그라운드 서브셸 내부에서 `OK=$((OK+1))`를 증가시켜도 부모 셸 변수로 전파되지 않는다.
  2. 최신 `grafana` 컨테이너 이미지가 셸을 제거한 distroless 기반이다.
  3. `zsh`는 `bash`와 달리 기본 변수 확장 시 공백 단어 분할(`SH_WORD_SPLIT`)을 수행하지 않는다.
- **해결**:
  1. [demo-02-canary-rollback.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/demos/demo-02-canary-rollback.sh)에서 응답 코드를 임시 파일(`/tmp/macprod-canary-traffic.log`)에 기록한 뒤 부모 셸이 집계하도록 수정했다.
  2. `kubectl port-forward`로 Prometheus(`19090`), Loki(`13100`), Tempo(`13200`) API를 직접 질의해 수집 증적(`http_requests_total=7967`, Loki streams `2`, Tempo traces `3`)을 확보했다.
  3. 스크립트는 `#!/usr/bin/env bash`로 고정하고 호스트 명령에서는 SSH 옵션을 명시적으로 분리 전달했다.

---

### Bug #14. `k6` 부하 직후 카나리 합산 에러율 희석으로 불량 `v2.0.0-bad` 승격 허용
- **발생 단계**: `k6` 3,067건 부하 테스트 직후 `Demo 2` 재실행 (`Rollout phase=Healthy` 통과)
- **관찰 현상**: `v2.0.0-bad`(`SIMULATE_ERROR_RATE=0.75`) 카나리가 중단되지 않고 전체 승격되어 `Rollout phase=Healthy`가 되었다.
- **원인**:
  1. 기존 `AnalysisTemplate` PromQL이 `sum(rate(http_requests_total{namespace="apps",status=~"5.."}[1m])) / sum(rate(...[1m]))`처럼 네임스페이스 합산 비율을 계산했다. 직전 `k6`가 Stable(`v1.0.0`) 파드에 쏟아부은 수천 건의 `200 OK`가 `[1m]` 윈도우에 남아 카나리 5xx 오류 비율을 `10%` 미만으로 희석시켰다.
  2. 또한 파드별 최소값을 계산할 때 트래픽이 없는 유휴 파드(`rate=0`)를 `> 0.01`로 거르지 않으면 `0 / clamp_min(0, 0.001) = 0.0`이 되어 정상 파드도 실패 처리되는 함정이 있다.
- **해결**: [analysis-template.yaml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/apps/order-service/k8s/base/analysis-template.yaml)을 활성 파드(`rate > 0.01`) 기준 **파드별 최저 성공률(`min` per-pod)** 쿼리로 재작성하고, [demo-02-canary-rollback.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/demos/demo-02-canary-rollback.sh)에 `ABORTED=1` 미충족 시 `exit 1` 강제 검증을 추가해 `200=130, non-200=20` 조건에서 즉시 `RolloutAborted` 자동 롤백을 확인했다.

---

### Bug #15. Ansible 플레이북 내 Python f-string 중괄호(`{{`)와 Jinja2 템플릿 문법 충돌
- **발생 단계**: `make reconcile` (`04-reconcile-ip-drift.yml` CoreDNS 동기화 태스크)
- **관찰 현상**:
  ```text
  fatal: [macprod-cp-1 -> localhost]: FAILED! => {"msg": "template error while templating string: expected token ':', got '}' ... hosts {{ ... {ops_ip} ... }}"}
  ```
- **원인**: Ansible은 태스크의 `shell:` 문자열을 실행 전 Jinja2로 먼저 파싱하므로, 인라인 Python 스크립트 안의 f-string 이스케이프 `{{` / `}}`가 Jinja2 표현식으로 오인되었다.
- **해결**: [04-reconcile-ip-drift.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/playbooks/04-reconcile-ip-drift.yml)의 Python heredoc에서 f-string 중괄호를 제거하고 일반 문자열 결합(`+`)으로 교체한 뒤 `make reconcile` 전체 7개 VM `failed=0` 통과를 확인했다.

---

### Bug #16. VM 콜드 부팅 직후 Vault `docker-proxy` 조기 수락 레이스로 `init.json` 0바이트 절단
- **발생 단계**: Mac 약 20시간 절전/중지 후 `macprod-ops` 재부팅 및 `macprod-ops-bootstrap.service` 실행
- **관찰 현상**:
  ```text
  macprod-ops-bootstrap.service: Failed with result 'exit-code' (status=2)
  dial tcp 127.0.0.1:8200: connect: connection refused
  ```
  동시에 `/opt/macprod/vault/init.json`이 0바이트로 덮어써져 기존 Vault 볼륨(`/vault/file`)은 초기화된 상태인데 Unseal 키와 Root Token 유실이 발생했다.
- **원인**: 컨테이너 재기동 직후 호스트의 `docker-proxy`가 `:8200` TCP 포트를 먼저 열고 내부 Vault 프로세스가 HTTP 리스너를 열기 전에 연결을 끊었다. 기존 [bootstrap-ops.sh.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/bootstrap-ops.sh.j2)의 `jq -r '.initialized // false'`가 빈 응답에서 `false`를 반환하자 `vault operator init ... > init.json` 리다이렉션이 기존 파일을 먼저 Truncate한 뒤 실패했다.
- **해결**:
  1. `curl -s "$VAULT_ADDR/v1/sys/health" | jq -e 'has("initialized")'`가 유효한 JSON 키를 반환할 때까지 최대 90초 대기하도록 수정했다.
  2. 초기화 출력은 `mktemp` 임시 파일에 먼저 기록하고 `.unseal_keys_b64[0]` 및 `.root_token` 존재 검증을 통과한 경우에만 `init.json`으로 원자적 `mv`하며 `init.json.bak` 사본을 보존하도록 개선했다.

---

### Bug #17. `argo-rollouts` 오프라인 재기동 시 GitHub 플러그인 재다운로드 실패(51회 백오프)
- **발생 단계**: 오프라인·장시간 절전 복귀 후 `argo-rollouts` 컨트롤러 파드 재시작
- **관찰 현상**: `argo-rollouts`가 51회 재시작하며 `gatewayapi-plugin-linux-arm64` 다운로드 실패로 트래픽 제어 불가.
- **원인**: [install-core.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/bootstrap/install-core.sh)가 `argo-rollouts-config`의 `gatewayAPI` 플러그인 URL을 외부 `github.com` 릴리스로 지정해 두었기 때문에, 파드가 재스케줄/재시작될 때마다 임시 컨테이너 파일시스템으로 외부 다운로드를 재시도했다.
- **해결**:
  1. [bootstrap-ops.sh.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/bootstrap-ops.sh.j2)가 `gatewayapi-plugin-linux-arm64`를 `macprod-ops` 로컬 `SeaweedFS Filer`(`http://127.0.0.1:8888/assets/gatewayapi-plugin-linux-arm64`)에 업로드·캐싱하도록 변경했다.
  2. [install-core.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/bootstrap/install-core.sh)와 라이브 `argo-rollouts-config`를 `http://s3.macprod.internal:8888/assets/gatewayapi-plugin-linux-arm64`로 전환해 재기동 시 `163.8ms` 내 로컬 다운로드를 확인했다.

---

### Bug #18. `tempo-0` Parquet WAL 컴팩션 중 `OOMKilled` (`512Mi` 상한 부족)
- **발생 단계**: `k6` 부하 및 트레이스 적재 누적 후 `tempo-0` 재시작·WAL 리플레이
- **관찰 현상**: `tempo-0` 파드가 `exitCode: 137`(`OOMKilled`)으로 116회 반복 재시작되며 `flush.go:267 completing block` 구간에서 중단되었다.
- **원인**: [11-tempo.yaml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/platform/gitops/apps/11-tempo.yaml)의 `limits.memory: 512Mi`가 `vParquet4` 블록 컴팩션 및 인제스터 WAL 리플레이 피크 메모리 수요를 감당하지 못했다.
- **해결**: `11-tempo.yaml`의 메모리 상한을 `1536Mi`로 상향하고 Gitea GitOps 반영 후 `tempo-0` WAL 리플레이·블록 컴팩션(`completing block duration=253.897ms`) 및 `Synced / Healthy` 복구를 확인했다.

---

### Bug #19. `systemd` `Type=oneshot` + `Restart=on-failure` 유닛 구성 오류
- **발생 단계**: `macprod-ops-bootstrap.service` 자동 재시도 설정 검증
- **관찰 현상**: `systemd-analyze verify macprod-ops-bootstrap.service`에서 `Type=oneshot` 서비스의 `Restart=on-failure` 거부 및 `[Service]` 섹션 `StartLimit*` 무시 경고가 발생했다.
- **원인**: `systemd` 255는 `Type=oneshot`에 `Restart=on-failure`를 허용하지 않으며 `StartLimitIntervalSec`/`StartLimitBurst`는 `[Unit]` 섹션에 선언해야 적용된다.
- **해결**: [ops-stack/tasks/main.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/tasks/main.yml)의 유닛을 `Type=simple`로 전환하고 `StartLimit*` 지시문을 `[Unit]`으로 이동해 `systemd-analyze verify` 경고 0건을 확인했다.

---

### Bug #20. macOS 번들 GNU Make `3.81` `.ONESHELL:` 미지원 구문 오류
- **발생 단계**: `make doctor` 사전 점검 타깃 실행
- **관찰 현상**: `/bin/sh: -c: line 1: syntax error: unexpected end of file` 및 `@if` 실행 실패.
- **원인**: macOS 기본 `/usr/bin/make`는 GNU Make `3.81`이므로 `3.82+` 기능인 `.ONESHELL:`을 무시하고 멀티라인 `for`/`if` 레시피를 줄 단위 서브셸로 쪼개 실행한다.
- **해결**: `Makefile`의 `.ONESHELL:` 의존 로직을 제거하고 [ops-vm-ctl.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/ops-vm-ctl.sh) `doctor` 서브커맨드로 위임했으며, `04-reconcile-ip-drift.yml`에도 Vault `vault.hcl` · `auth/kubernetes/config` · `cilium-config` `k8s-service-host` 동기화를 보강했다.

---

### Bug #21. `make stop && make reconcile` 직후 SSH · `/readyz` 레이스 및 `Unknown` 파드 일괄 삭제 폭주
- **발생 단계**: 7개 VM 전체 정지(`make stop`) 직후 콜드 복구(`make reconcile`) 실측 테스트
- **관찰 현상**:
  1. 1차 테스트에서 `start-all`이 `tart ip`만 확인하고 즉시 종료해 Ansible이 `sshd` 기동 전 `:22 Connection refused`로 실패했다.
  2. 2차 테스트에서 `/readyz` 확인 직후 kubelet이 샌드박스를 재동기화하기 전 일시적으로 `Unknown` 표시된 모든 파드(`cilium`, `kyverno`, `order-db`, `order-service`)를 일괄 강제 삭제하자 40여 개 파드가 동시 재생성되며 Cilium `[429] putEndpointIdTooManyRequests` 및 Kyverno 웹훅 `no route to host` 연쇄 지연이 발생했다.
- **해결**:
  1. [ops-vm-ctl.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/ops-vm-ctl.sh)에 `wait_ssh()`를 추가해 `start-all`이 전 VM SSH 포트/키 인증 준비까지 대기하도록 수정했다.
  2. [04-reconcile-ip-drift.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/playbooks/04-reconcile-ip-drift.yml)에 `Wait for kube-apiserver via HAProxy /readyz`(최대 180초 재시도) 및 `kubectl wait --for=condition=Ready node --all`을 선행하고, 일시 `Unknown` 대신 영구 종료 상태인 `status.phase=Failed` 파드만 정리하도록 교정했다.

---

### Bug #22. `tart stop macprod-ops` 종료 시 SeaweedFS 0바이트 `.sdx` 잔류로 `cnpg-backups` S3 읽기 `404`/`500` 장애
- **발생 단계**: `make stop && make reconcile` 후 `CloudNativePG` Standby 파드(`order-db-2`, `order-db-3`) WAL 복구 단계
- **관찰 현상**:
  ```text
  barman-cloud-wal-restore: An error occurred (InternalError) when calling GetObject ... 00000003.history
  seaweedfs: failed to stream cnpg-backups/order-db/wals/00000003.history.gz: 404 Not Found
  ```
  디스크에는 `cnpg-backups_21.dat`(300KB)와 `.idx`(112B)가 온전한데도 같은 볼륨에 **0바이트** `cnpg-backups_15.sdx`, `_20.sdx`, `_21.sdx` 파일이 생성되어 있었다.
- **원인**: SeaweedFS `4.55`는 볼륨 닫힘/ReadOnly 전환 시 정렬 인덱스 `.sdx` 파일을 기록한다. 클러스터 워크로드가 실행 중인 상태에서 `tart stop macprod-ops`가 VM을 종료하면 `.sdx` 기록 도중 절단된 0바이트 파일이 남고, 재기동 시 SeaweedFS가 정상 `.idx` 대신 빈 `.sdx`를 로드해 해당 볼륨을 `ReadOnly` 빈 인덱스로 마운트한다.
- **해결**:
  1. [ops-vm-ctl.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/ops-vm-ctl.sh)의 `stop-all`이 Worker/CP VM을 먼저 정지한 뒤 `macprod-ops`에서 `docker compose stop -t 25`를 선행해 `.sdx`를 정상 크기로 Flush한 후 VM을 끄도록 변경했다.
  2. [docker-compose.yml.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/docker-compose.yml.j2)에 `stop_grace_period: 30s`를 부여했다.
  3. [bootstrap-ops.sh.j2](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/roles/ops-stack/templates/bootstrap-ops.sh.j2)가 기동 전 비정상 `0바이트 .sdx`를 자동 삭제하고 `docker compose up -d`로 컨테이너를 기동하도록 방어 로직을 추가해, 재기동 직후 `s3_hist_read=200`·`non_ready=0`·`14/14 Healthy` 수렴을 검증했다.

---

### Bug #23. Ubuntu `50-cloud-init.conf`의 OpenSSH `first-match-wins` 우선순위로 `PasswordAuthentication no` 무력화
- **발생 단계**: Vault SSH CA(`05-configure-ssh-ca.yml`) 적용 전 `sshd` 현재 유효 설정 감사 (`sudo sshd -T`)
- **관찰 현상**: `/etc/ssh/sshd_config.d/60-cloudimg-settings.conf`에 `PasswordAuthentication no`가 있는데도 실제 `sudo sshd -T` 출력은 `passwordauthentication yes`로 확인되었다.
- **원인**: `/etc/ssh/sshd_config`의 `Include /etc/ssh/sshd_config.d/*.conf`는 사전순 먼저 등장한 설정이 최종 효력을 갖는 `first-match-wins` 규칙을 따르므로 `50-cloud-init.conf`(`PasswordAuthentication yes`)가 `60-*`보다 우선 적용되었다. 만약 SSH CA 드롭인을 `60-` 이후 번호로 만들었으면 패스워드 인증 차단이 조용히 무시될 수 있었다.
- **해결**: [05-configure-ssh-ca.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/playbooks/05-configure-ssh-ca.yml)이 드롭인 파일명을 **`10-macprod-ssh-ca.conf`** (`50-`보다 선순위)로 배치해 `sudo sshd -T` 기준 `passwordauthentication=no` 적용을 검증했다.

---

### Bug #24. Vault SSH CA 비인증 조회 엔드포인트 오용(`/config/ca` `403 Forbidden`)
- **발생 단계**: `make ssh-ca` (`05-configure-ssh-ca.yml`) 최초 실행
- **관찰 현상**:
  ```text
  fatal: [localhost]: FAILED! => {"json": {"errors": ["permission denied"]}, "msg": "Status code was 403 and not [200, 404]: HTTP Error 403: Forbidden", "status": 403, "url": "http://192.168.67.25:8200/v1/ssh-client-signer/config/ca"}
  ```
- **원인**: Vault SSH 시크릿 엔진에서 `/v1/<mount>/config/ca`는 인증 토큰이 필요한 경로이며, 인증 없이 CA 공개키를 조회하는 표준 엔드포인트는 JSON이 아니라 `text/plain` 원문을 반환하는 `/v1/ssh-client-signer/public_key`이다.
- **해결**: [05-configure-ssh-ca.yml](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/infra/ansible/playbooks/05-configure-ssh-ca.yml)이 `/v1/ssh-client-signer/public_key`를 조회해 `.runtime/ssh-ca` 디렉터리 생성 후 `vault_ssh_ca_resp.content | trim`(`^ssh-` 정규식 확인)으로 저장하도록 수정해 7개 VM `failed=0` 배포를 완료했다.

---

### Bug #25. `ops-vm-ctl.sh` `write_ssh_config()` 전역 `vm` 덮어쓰기 및 `Makefile` `CMD` 셸 분할
- **발생 단계**: `make ssh-cert` 이후 원커맨드 SSH 접속 헬퍼 테스트 (`./scripts/ops-vm-ctl.sh ssh macprod-wk-1 "hostname && whoami"`, `make ssh VM=macprod-wk-1 CMD="hostname && whoami"`)
- **관찰 현상**:
  1. 1차 실행 시 `ssh: connect to host  port 22: Connection refused` 오류로 빈 호스트명 연결을 시도하며 `exit code 255` 실패.
  2. `write_ssh_config()` 수정 후에도 `make ssh VM=macprod-wk-1 CMD="hostname && whoami"` 실행 시 `macprod-wk-1`은 원격에서, `whoami`는 Mac 로컬 호스트(`ywlee`)에서 실행되었다.
- **원인**:
  1. `write_ssh_config()` 함수 내부 `while IFS= read -r vm` 루프가 `local` 선언 없이 전역 `vm` 변수를 사용해, 루프 EOF 시 바깥 `ssh` 케이스의 `vm="macprod-wk-1"`을 빈 문자열로 덮어썼다.
  2. [Makefile](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/Makefile)의 `ssh` 레시피가 `$(CMD)`를 따옴표 없이 전달해 셸이 `&&`를 로컬 명령 연결로 해석했다.
- **해결**: [ops-vm-ctl.sh](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/scripts/ops-vm-ctl.sh)의 `write_ssh_config()` 루프 변수를 `local v_name`으로 격리하고, [Makefile](file:///Users/ywlee/sideproejct/INFRA/vol1_Infra/Makefile)에서 `$(if $(CMD),"$(CMD)",)`로 인자를 보호해 원격 VM 내 `macprod-wk-1` / `admin` 정상 실행을 확인했다. Also `ssh-keygen -Lf` 출력 파싱 시 `Principals:` 다음 줄에 실제 Principal(`admin`)이 찍히므로 `grep -A1 "Principals:"`로 교정했다.
