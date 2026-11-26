# 01. 아키텍처 및 기술 스택 선정 근거 (ADR)

본 문서는 `Apple M4 Max` (`16코어`, `128 GB` 통합 메모리, `macOS 15.7.4`) 환경에 구축한 **안 A: 단일 HA 코어 (`Prod-in-a-Mac`)** 아키텍처를 **최하위 하드웨어(L0)부터 상위 플랫폼 서비스(L6)까지 Bottom-Up 계층 순서**로 정리하고, 각 기술 스택의 선정 이유, 포기한 대안, 그리고 실무 클라우드(AWS EKS)와의 매핑(Cloud Parity)을 기록한다.

> 각 계층을 PPT `16:9` 슬라이드로 분할한 아키텍처 덱은 [00-handover-guide.md](./00-handover-guide.md) 및 [docs/diagrams/](./diagrams/)에서 확인할 수 있다.

---

## 1. Bottom-Up 계층 구조 및 VM별 스펙·역할

단일 노트북 실습에서 흔히 쓰는 `Kind`/`Docker Desktop` 단일 노드를 피하고, 실제 프로덕션 장애 시나리오(`etcd` 2/3 쿼럼 유지, L4 로드밸런서 헬스체크 전환, PostgreSQL Primary Failover, 클러스터 외부 백업 내구성)를 재현하기 위해 **물리 호스트 → Tart 하이퍼바이저 → 7개 ARM64 리눅스 VM**을 계층화해 구축했다.

| 계층 / VM | vCPU | RAM | Disk (Sparse) | 역할 및 정의 위치 |
|---|---:|---:|---:|---|
| **L0 · 물리 호스트** | 16 | 128 GB | 969 Gi 여유 | `Apple M4 Max` (`ARM64 / aarch64`, `macOS 15.7.4`, 호스트 메모리 ~80 GB 여유 · Swap 0) |
| **L1 · 하이퍼바이저** | — | — | — | `Cirrus Labs Tart v2.31.0` (`Apple Virtualization.framework / HVF`, `vmnet Softnet 192.168.67.0/24`) — [ops-vm-ctl.sh](../scripts/ops-vm-ctl.sh#L32) |
| **L2/L3 · `macprod-ops`** | 2 | 6 GB | 35 GB | 외부 관리 평면 & Bastion (`HAProxy`, `SeaweedFS`, `Zot`, `Gitea`, `Vault+SSH CA`, `k6`) — [cluster.yaml#L41-45](../infra/config/cluster.yaml#L41-L45) |
| **L2/L4 · `macprod-cp-1`** | 2 | 4 GB | 30 GB | HA Control Plane Bootstrap Leader (`bootstrap: true`), Stacked `etcd #1`, 초기/데모 `etcd` S3 백업 — [cluster.yaml#L46-51](../infra/config/cluster.yaml#L46-L51) |
| **L2/L4 · `macprod-cp-2`** | 2 | 4 GB | 30 GB | HA Control Plane #2 (`etcd #2`), `Demo 1` 강제 정지 대상, `etcd-s3-backup` cron (`02:15`) — [cluster.yaml#L52-57](../infra/config/cluster.yaml#L52-L57) |
| **L2/L4 · `macprod-cp-3`** | 2 | 4 GB | 30 GB | HA Control Plane #3 (`etcd #3`), `cp-2` 장애 시 `2/3` Raft 쿼럼 유지, `02:15` cron — [cluster.yaml#L58-63](../infra/config/cluster.yaml#L58-L63) |
| **L2/L6 · `macprod-wk-1..3`** | 각 3 (`총 9`) | 각 10 GB (`총 30`) | 각 45 GB (`총 135`) | `worker=true` 워크로드 풀: `Cilium Envoy :30080`, `order-service` ×3, `order-db` ×3, GitOps/보안/DR/관측성 — [cluster.yaml#L64-78](../infra/config/cluster.yaml#L64-L78) |
| **VM 합계** | **17 vCPU** | **48 GB** | **260 GB** | 단일 SSOT 정의: [infra/config/cluster.yaml](../infra/config/cluster.yaml) |

### 핵심 설계 원칙
1. **외부 관리 평면 (`macprod-ops`) 분리**: Terraform Remote State(`SeaweedFS S3`), 컨테이너 레지스트리(`Zot`), GitOps 원격 저장소(`Gitea`), 시크릿·SSH CA 저장소(`Vault`), L4/L7 로드밸런서(`HAProxy`)를 Kubernetes 밖에 두어 순환 의존성과 클러스터 전소 시 백업 동반 유실을 막는다.
2. **내부 도메인 추상화 (`*.macprod.internal`)**: 전 노드 `/etc/hosts`와 클러스터 `CoreDNS`가 `api`, `gitea`, `zot`, `s3`, `vault`, `order`, `argocd`, `grafana`, `hubble`을 현재 `macprod-ops` IP로 해석한다. GitOps 매니페스트에는 IP를 하드코딩하지 않아 DHCP IP 변동 시 `make reconcile` 한 번으로 복구된다.
3. **100% ARM64 네이티브 원칙**: 컨트롤 플레인부터 데모 앱(`order-service`)까지 모두 `linux/arm64` 이미지로 통일해 Rosetta/QEMU 에뮬레이션 오버헤드를 없애고 AWS Graviton / GCP Tau 환경과 동일한 실행 특성을 확보한다.

---

## 2. 계층별 기술 스택 선정 근거 및 대안 비교 (Bottom-Up ADR)

### Layer 1~2 — 하이퍼바이저, 게스트 OS & IaC 프로비저닝
| 구분 | 선정 스택 | 검토한 대안 (미채택 사유) | Cloud Parity (AWS) |
|---|---|---|---|
| 하이퍼바이저 (L1) | **Tart `v2.31.0` (`Apple Virtualization.framework`)** | `Docker Desktop / Kind`(다중 `etcd` 커널/VM 장애 재현 불가), `UTM / QEMU`(소프트웨어 에뮬레이션 및 Terraform/CLI 자동화 불편) | EC2 하이퍼바이저 (Nitro) |
| 게스트 OS (L2) | **Ubuntu `24.04.4 LTS` ARM64 (`linux 6.17`)** | `Talos Linux`(불변 OS로 깔끔하나 `systemd`·`containerd`·`kubeadm`·`sshd` 내부 트러블슈팅 역량 습득에 비해 블랙박스) | Amazon Linux 2023 ARM64 |
| 프로비저닝 & 구성관리 | **Terraform `v1.5.7` + Ansible `2.18.14`** | 단일 `Bash` 스크립트(멱등성 부족·상태 추적 불가), `Pulumi`(인프라 표준 HCL 범용성 유지) | Terraform EKS + UserData |

* **하이퍼바이저(`Tart`) 선정 및 격리 설계**: Mac 커널의 Apple HVF 가속을 직접 쓰는 `Tart`를 통해 `128 GB` 호스트 중 `48 GB`만 쓰면서도 독립 리눅스 커널 7대를 네이티브 속도로 구동한다. `local-m4`와 `ops-vm-ctl.sh`는 [cluster.yaml](../infra/config/cluster.yaml)의 `macprod-*` 7대만 제어하도록 엄격히 한정했다.
* **2계층 Terraform 분리 이유**: `infra/terraform/local-m4`(로컬 state로 7-VM 생성·SSH 키·Ansible 인벤토리 생성)와 `infra/terraform/platform-state`(클러스터 외부 `SeaweedFS S3`를 `backend "s3"`로 사용해 Vault KV/K8s Auth/SSH CA·K8s 거버넌스 관리)를 분리해 상태 순환을 방지한다.

---

### Layer 3 — `macprod-ops` 외부 상태 저장소 · 공급망 · Load Testing
| 구분 | 선정 스택 | 검토한 대안 (미채택 사유) | Cloud Parity (AWS) |
|---|---|---|---|
| L4/L7 로드밸런서 | **HAProxy `3.0-alpine` (`macprod-ops`)** | `MetalLB / Cilium L2 Announcements`(Tart `--net-softnet` 필터가 비DHCP VIP/Gratuitous ARP를 차단함) | AWS NLB (`:6443`) + ALB (`:80`) |
| S3 오브젝트 스토리지 | **SeaweedFS `4.55`** | `MinIO`(커뮤니티 바이너리·Docker 배포 중단: `410 Gone` / `401`), `Garage`(초기 버킷·레이아웃 수동 구성 번거로움) | Amazon S3 |
| OCI 레지스트리 | **CNCF Zot `v2.1.2`** | `Harbor`(`goharbor/harbor-core:v2.11~v2.13` 공식 이미지가 `linux/amd64` 전용임을 매니페스트 API로 확인), `Registry v2`(웹 UI 부재) | Amazon ECR |
| 취약점 스캔 | **Trivy CLI** | `Clair`(단독 구성 복잡) | Amazon Inspector / Trivy CI |
| GitOps 저장소 | **Gitea `1.22`** | 외부 `GitHub`만 사용(로컬 데모 시 외부 PAT·터널링 의존) | GitHub / CodeCommit |
| 부하 테스트 | **Grafana `k6 v2.4.0`** | `JMeter`(JVM 힙 과점유·XML 기반 코드화 한계), `Locust`(Python GIL 멀티프로세스 분산 필요), `k6-operator`(워커 자원 경합) | 동일 (`k6`) |

* **SeaweedFS S3 통합 검증**: 단일 컨테이너에서 `terraform-state`(Terraform S3 백엔드 + `etcd` 스냅샷), `cnpg-backups`(CloudNativePG WAL/Basebackup), `velero-backups`(Velero Kopia 백업), `loki-chunks` 및 `:8888/assets/`(`argo-rollouts` 플러그인 캐시)를 모두 처리한다. 콜드 종료 시 `0바이트 .sdx` 잔류 방어를 위해 `stop-all` 순차 Flush와 기동 전 `.sdx` 자가치유를 적용했다(`Bug #22`).
* **`k6 v2.4.0` 선정 및 `macprod-ops` 외부 배치 근거**:
  1. **ARM64 단일 바이너리 경량성**: [ops-stack/tasks/main.yml](../infra/ansible/roles/ops-stack/tasks/main.yml#L129-L138)에서 `/usr/local/bin/k6` Go 바이너리 1개로 설치해 `macprod-ops` (`2C / 6 GB`)에서도 JVM 부담 없이 `30 VUs` (`3,067 req`, `67.95 req/s`) 부하를 생성한다.
  2. **Load Testing as Code & SLO 게이트**: [canary-load.js](../tests/k6/canary-load.js#L4-L14)에서 `stages`(`10s→15 VU`, `25s→30 VU`, `10s→0`), `POST` 25% 혼합, `http_req_failed < 5%`, `p(95) < 500ms` 임계치를 Git으로 버전 관리한다.
  3. **외부 Bastion 배치**: 워커 내부 파드 실행 시 측정 대상과 CPU·네트워크를 경합하므로, `macprod-ops`에서 `BASE_URL=http://127.0.0.1` · `HOST_HEADER=order.macprod.internal`로 `HAProxy → Cilium Envoy → order-service → CNPG → LGTM+OTel` 전체 경로를 종단 검증한다.

---

### Layer 4~5 — 3-Master HA 컨트롤 플레인 & Cilium eBPF · Gateway API 경계
| 구분 | 선정 스택 | 검토한 대안 (미채택 사유) | Cloud Parity (AWS) |
|---|---|---|---|
| K8s 코어 | **`kubeadm v1.32.13` Stacked `etcd` HA** | `k3s`(초기 구성은 단순하나 프로덕션 `kubeadm`·`etcdctl`·PKI SAN 트러블슈팅 구조와 상이) | Amazon EKS Control Plane |
| CNI & 서비스 메시 | **Cilium `1.20.5` (`eBPF`, `kube-proxy` 대체)** | `Flannel`(NetworkPolicy 미지원), `Calico`(eBPF·Hubble 통합 L7 관측성 측면에서 Cilium 우위) | Cilium CNI on EKS |
| 인그레스 | **Gateway API `v1.6.3` + Cilium Envoy (`hostNetwork`)** | `Ingress-Nginx`(유지보수 축소 및 Gateway API 표준 전환 추세) | AWS Load Balancer Controller / Gateway API |

* **왜 `gatewayAPI.hostNetwork.enabled=true`인가?**
  `vmnet Softnet` 환경에서는 게스트 VM이 비DHCP VIP를 광고할 수 없다. 따라서 워커 3노드(`node-role.kubernetes.io/worker=true`)에만 `hostNetwork` 포트 `30080`으로 Envoy 리스너를 띄우고, 외부 `HAProxy :80`이 `macprod-wk-1..3:30080`으로 라운드로빈 헬스체크(`http-check send`)를 수행하게 해 L2 ARP 제약 없이 멀티노드 인그레스 HA를 구현했다.

---

### Layer 6 — GitOps 배포 · 시크릿 · Zero-Trust SSH · 정책 · DB HA · DR · 관측성
| 구분 | 선정 스택 | 검토한 대안 (미채택 사유) | Cloud Parity (AWS) |
|---|---|---|---|
| GitOps CD | **ArgoCD `10.18.2` (App `v3.6.2`)** | `Flux CD`(UI 직관성 및 국내 채용 수요 기준 ArgoCD 우위), `Helm CLI` 직접 배포(드리프트 자동 복구 불가) | ArgoCD on EKS |
| 점진적 배포 | **Argo Rollouts `2.43.12` + `gatewayAPI` 플러그인 (`v0.18.0`)** | 기본 RollingUpdate(지표 기반 자동 중단/롤백 불가) | 동일 (EKS ALB/Gateway API 플러그인) |
| 시크릿 관리 | **HashiCorp Vault `1.18.3` (File Backend) + ESO `2.15.0`** | `Sealed Secrets`(동적 회전·중앙 감사 한계), `Vault -dev` 모드(재부팅 시 데이터 유실) | AWS Secrets Manager + ESO |
| SSH 접근 제어 | **Vault SSH CA (`ssh-client-signer`, `ed25519` 1~8h 단기 인증서)** | 정적 키+`sshpass` 단독 운영(회수·감사 불가), `Teleport`/`Smallstep`(별도 서버 증설 대비 기존 Vault 재활용 우위), `Ansible authorized_key`(만료 부재), `AWS SSM`/`Tailscale SSH`(포트 22 제거형) | AWS SSM Session Manager / Vault SSH CA |
| 정책 엔진 | **Kyverno `3.10.0` (`v1.20.0`, CEL `ValidatingPolicy`)** | `OPA Gatekeeper`(Rego 학습 비용 대비 K8s 네이티브 CEL 정책 호환성 우위) | 동일 (Kyverno / VAP) |
| HA RDBMS | **CloudNativePG `0.29.2` (`1.30.2`, PG `16.6` × 3)** | `Bitnami PostgreSQL Helm`(자동 Primary 승격·PITR·선언적 클러스터링 한계) | Amazon RDS / Aurora Multi-AZ |
| 백업 & DR | **Velero `12.2.5` (`v1.18.2`, Kopia) + `etcd-s3-backup`** | Host 스냅샷 단독(네임스페이스·RBAC·PVC 동반 이식 복구 불가) | AWS Backup / Velero EBS Snapshot |
| 관측성 스택 | **Prometheus (`kps 93.9.0`) + Loki `7.7.0` + Promtail `6.17.1` + Tempo `1.24.4` + OTel `0.182.0`** | `ELK/Elasticsearch`(로컬 환경에서 과도한 8~12 GB 힙 점유) | Amazon Managed Prometheus/Grafana 또는 동일 스택 |

* **SSH 키 관리·배포 방식 고찰 및 Vault SSH CA 최종 결정**:
  1. **초기 정적 키 + `sshpass` 방식의 한계**: 최초 부트스트랩([ops-vm-ctl.sh](../scripts/ops-vm-ctl.sh) `ensure-vm`)에는 `admin/admin`으로 `macprod_ed25519`를 심는 방식이 단순하지만, 팀 인수인계 시 단일 키 공유 위험, 7개 VM의 `authorized_keys` 일괄 회수 난이도, 접속자별 발급 감사 로그 부재 문제가 있다.
  2. **대안 비교 결론**: `Teleport`나 `Smallstep`을 별도로 띄우는 대신 이미 `macprod-ops:8200`에서 가동 중인 `Vault 1.18.3`에 `ssh-client-signer` 마운트만 추가하면 추가 데몬 없이 단기 SSH 인증서 체계를 완성할 수 있다.
  3. **보안·자동화 공존 설계**: [platform-state/main.tf](../infra/terraform/platform-state/main.tf#L156-L194)가 `ed25519` SSH CA와 `macprod-admin` 역할(`1h`, max `8h`)·최소 권한 정책(`ssh-client-sign`)을 생성하고, [05-configure-ssh-ca.yml](../infra/ansible/playbooks/05-configure-ssh-ca.yml)이 전 7개 VM에 `/etc/ssh/trusted-user-ca-keys.pem`과 `/etc/ssh/sshd_config.d/10-macprod-ssh-ca.conf`(`10-` 선순위로 `50-cloud-init.conf`의 `PasswordAuthentication yes` 덮어쓰기)를 배포한다. 내부 자동화 키(`macprod_ed25519`)와 운영자 단기 인증서 키(`macprod_user_ed25519-cert.pub`)는 분리했다.
* **Kyverno `v1.20` CEL 정책 전환 배경**: Kyverno `v1.20`은 레거시 `kyverno.io/v1 ClusterPolicy` 실행을 중단하고 `policies.kyverno.io/v1 ValidatingPolicy`(CEL)만 허용한다. 이에 `:latest` 차단(`disallow-latest-tag`), 리소스 상·하한 강제(`require-resource-requests-limits`), 권한 상승 차단(`disallow-privilege-escalation`, `cnpg.io/cluster` 예외)을 CEL 정책으로 구현했다.
* **Loki / Tempo 메모리 최적화 선택**: `loki 7.7.0`은 `deploymentMode: SingleBinary` + 캐시/`test` 비활성화로 경량화(`512Mi`)했고, `tempo 1.24.4`는 Parquet WAL 컴팩션 피크 OOM(`Bug #18`) 해소를 위해 메모리 상한을 `1536Mi`로 조정했다.

---

## 3. Cloud Parity 이식 구조 (`local-m4` → `cloud-aws-eks`)

로컬 Mac에서 검증한 워크로드와 GitOps 설정을 AWS EKS(Graviton ARM64)로 옮길 때 변경되는 부분은 **오버레이와 인프라 모듈뿐**이며 핵심 매니페스트는 공유한다.

* 인프라 프로비저닝: [infra/terraform/local-m4](../infra/terraform/local-m4/main.tf) → [infra/terraform/cloud-aws-eks](../infra/terraform/cloud-aws-eks/main.tf)
* 앱 배포 오버레이: [apps/order-service/k8s/overlays/local-m4](../apps/order-service/k8s/overlays/local-m4/kustomization.yaml) → [apps/order-service/k8s/overlays/cloud-eks](../apps/order-service/k8s/overlays/cloud-eks/kustomization.yaml)
