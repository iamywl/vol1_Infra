SHELL := /usr/bin/env bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TF_LOCAL := $(ROOT_DIR)/infra/terraform/local-m4
TF_PLATFORM := $(ROOT_DIR)/infra/terraform/platform-state
ANSIBLE_DIR := $(ROOT_DIR)/infra/ansible
KUBECONFIG := $(ROOT_DIR)/.kube/config

.PHONY: help doctor up tf-vms ansible-all ops k8s bootstrap platform deploy status stop reconcile destroy ssh-ca ssh-cert ssh demo-ha demo-canary demo-db demo-security demo-velero demo-ssh

help:
	@echo "Option A: Prod-in-a-Mac (Single HA Core)"
	@echo "  make doctor        - Mac 아키텍처, RAM/디스크, 필수 CLI 사전 점검"
	@echo "  make tf-vms        - Layer 1 Terraform으로 7개 Tart VM 생성·기동 및 Ansible 인벤토리 생성"
	@echo "  make ansible-all   - OS 튜닝, ops-vm 스택(HAProxy/SeaweedFS/Zot/Gitea/Vault), 3-Master HA K8s 구축"
	@echo "  make bootstrap     - Day-1 Cilium eBPF, Gateway API, local-path, ArgoCD, Argo Rollouts 설치"
	@echo "  make platform      - Layer 2 Terraform(S3 백엔드 + Vault + Quota/RBAC) 및 Gitea GitOps 동기화"
	@echo "  make up            - 위 전체 과정 한 번에 실행 (Zero-to-Ready)"
	@echo "  make status        - VM 상태, 노드/파드, 엔드포인트 확인"
	@echo "  make reconcile     - Mac 재부팅 후 DHCP IP 드리프트 멱등 복구"
	@echo "  make ssh-ca        - 전 7개 VM에 Vault SSH CA 신뢰 및 PasswordAuth 차단 배포"
	@echo "  make ssh-cert      - Vault에서 단기 SSH 인증서(기본 TTL 1h, TTL=4h 지정 가능) 발급"
	@echo "  make ssh VM=<이름> - 단기 인증서 자동 갱신 후 지정 VM에 SSH 접속"
	@echo "  make stop          - macprod-* VM 안전 종료"
	@echo "  make destroy       - macprod-* VM 및 로컬 상태 전체 삭제"
	@echo "  make demo-ha       - Demo 1: Control Plane 1대 강제 종료 무중단 & etcd 백업"
	@echo "  make demo-canary   - Demo 2: 5xx 오류 v2 카나리 배포 시 Argo Rollouts 자동 롤백"
	@echo "  make demo-db       - Demo 3: CloudNativePG Primary Failover & WAL PITR 복구"
	@echo "  make demo-security - Demo 4: Vault->ESO 동적 반영 & Kyverno 비준수 파드 차단"
	@echo "  make demo-velero   - Demo 5: 네임스페이스 삭제 후 SeaweedFS S3 기반 Velero 복구"
	@echo "  make demo-ssh      - Demo 6: Vault SSH CA 단기 인증서 기반 무키·무패스워드 접속 검증"

doctor:
	@$(ROOT_DIR)/scripts/ops-vm-ctl.sh doctor

tf-vms:
	cd $(TF_LOCAL) && terraform init -upgrade=false
	cd $(TF_LOCAL) && terraform apply -auto-approve

ansible-all: ops k8s

ops:
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/01-prepare-all.yml
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/02-ops-node.yml

k8s:
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/03-k8s-cluster.yml

bootstrap:
	$(ROOT_DIR)/platform/bootstrap/install-core.sh

platform:
	$(ROOT_DIR)/scripts/bootstrap-all.sh sync-platform

up: tf-vms ansible-all bootstrap platform status

reconcile:
	$(ROOT_DIR)/scripts/ops-vm-ctl.sh start-all
	$(ROOT_DIR)/scripts/bootstrap-all.sh refresh-inventory
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/04-reconcile-ip-drift.yml

status:
	$(ROOT_DIR)/scripts/ops-vm-ctl.sh status
	@if [ -f "$(KUBECONFIG)" ]; then \
		echo ""; \
		KUBECONFIG="$(KUBECONFIG)" kubectl get nodes -o wide; \
		echo ""; \
		KUBECONFIG="$(KUBECONFIG)" kubectl get pods -A; \
	fi

stop:
	$(ROOT_DIR)/scripts/ops-vm-ctl.sh stop-all

destroy:
	cd $(TF_LOCAL) && terraform destroy -auto-approve || true
	rm -rf $(ROOT_DIR)/.runtime $(ROOT_DIR)/.kube

demo-ha:
	$(ROOT_DIR)/scripts/demos/demo-01-ha-controlplane.sh

demo-canary:
	$(ROOT_DIR)/scripts/demos/demo-02-canary-rollback.sh

demo-db:
	$(ROOT_DIR)/scripts/demos/demo-03-db-failover-pitr.sh

demo-security:
	$(ROOT_DIR)/scripts/demos/demo-04-vault-eso-kyverno.sh

demo-velero:
	$(ROOT_DIR)/scripts/demos/demo-05-velero-dr.sh

ssh-ca:
	$(ROOT_DIR)/scripts/bootstrap-all.sh refresh-inventory
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/05-configure-ssh-ca.yml

ssh-cert:
	$(ROOT_DIR)/scripts/ops-vm-ctl.sh ssh-cert $(TTL)

ssh:
	@if [ -z "$(VM)" ]; then echo "Usage: make ssh VM=macprod-wk-1 [CMD=\"hostname\"]" >&2; exit 1; fi
	$(ROOT_DIR)/scripts/ops-vm-ctl.sh ssh $(VM) $(if $(CMD),"$(CMD)",)

demo-ssh:
	$(ROOT_DIR)/scripts/demos/demo-06-vault-ssh-ca.sh
