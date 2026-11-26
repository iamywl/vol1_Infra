terraform {
  required_version = ">= 1.5.0"

  # Remote state stored off-cluster on SeaweedFS S3 (macprod-ops:8333)
  # Pass endpoint/credentials via -backend-config generated at runtime.
  backend "s3" {
    bucket                      = "terraform-state"
    key                         = "platform/terraform.tfstate"
    region                      = "us-east-1"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    force_path_style            = true
  }

  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.4"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.33"
    }
  }
}

provider "vault" {
  address = var.vault_addr
  token   = var.vault_token
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

# 1. Vault KV v2 Secret Engine + Initial App/DB Secrets
resource "vault_mount" "kv" {
  path        = "secret"
  type        = "kv"
  options     = { version = "2" }
  description = "KV v2 store for Kubernetes External Secrets"
}

resource "vault_kv_secret_v2" "order_db_creds" {
  mount      = vault_mount.kv.path
  name       = "apps/order-service"
  depends_on = [vault_mount.kv]

  data_json = jsonencode({
    DB_USER     = "orderapp"
    DB_PASSWORD = var.order_db_password
    DB_NAME     = "orders"
    API_KEY     = var.order_api_key
    S3_ACCESS   = var.s3_access_key
    S3_SECRET   = var.s3_secret_key
  })
}

# 2. Kubernetes Authentication Backend for External Secrets Operator (ESO)
resource "vault_auth_backend" "kubernetes" {
  type = "kubernetes"
  path = "kubernetes"
}

resource "vault_kubernetes_auth_backend_config" "k8s_config" {
  backend                = vault_auth_backend.kubernetes.path
  kubernetes_host        = var.k8s_api_endpoint
  kubernetes_ca_cert     = var.k8s_ca_cert
  token_reviewer_jwt     = var.vault_reviewer_jwt
  disable_local_ca_jwt   = true
}

resource "vault_policy" "eso_apps_read" {
  name   = "eso-apps-read"
  policy = <<-EOT
    path "secret/data/apps/*" {
      capabilities = ["read"]
    }
    path "secret/metadata/apps/*" {
      capabilities = ["list", "read"]
    }
  EOT
}

resource "vault_kubernetes_auth_backend_role" "eso_role" {
  backend                          = vault_auth_backend.kubernetes.path
  role_name                        = "eso-apps-role"
  bound_service_account_names      = ["external-secrets-vault-auth", "external-secrets"]
  bound_service_account_namespaces = ["apps", "external-secrets"]
  token_ttl                        = 3600
  token_policies                   = [vault_policy.eso_apps_read.name]
}

# 3. Kubernetes Namespace Governance (Cloud Parity with EKS)
locals {
  managed_namespaces = {
    apps          = { environment = "production", pss = "baseline", pss_warn = "restricted" }
    observability = { environment = "platform", pss = "privileged", pss_warn = "privileged" }
    security      = { environment = "platform", pss = "privileged", pss_warn = "privileged" }
    velero        = { environment = "platform", pss = "privileged", pss_warn = "privileged" }
  }
}

resource "kubernetes_namespace" "managed" {
  for_each = local.managed_namespaces

  metadata {
    name = each.key
    labels = {
      "managed-by"                         = "terraform"
      "environment"                        = each.value.environment
      "pod-security.kubernetes.io/enforce" = each.value.pss
      "pod-security.kubernetes.io/warn"    = each.value.pss_warn
    }
  }
}

resource "kubernetes_resource_quota" "apps_quota" {
  metadata {
    name      = "apps-quota"
    namespace = kubernetes_namespace.managed["apps"].metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = "6"
      "requests.memory" = "8Gi"
      "limits.cpu"      = "12"
      "limits.memory"   = "16Gi"
      "pods"            = "40"
    }
  }
}

resource "kubernetes_limit_range" "apps_limits" {
  metadata {
    name      = "apps-default-limits"
    namespace = kubernetes_namespace.managed["apps"].metadata[0].name
  }

  spec {
    limit {
      type = "Container"
      default = {
        cpu    = "500m"
        memory = "512Mi"
      }
      default_request = {
        cpu    = "100m"
        memory = "128Mi"
      }
    }
  }
}

# 4. Vault SSH Client Signer (CA for Short-Lived Signed SSH Certificates)
resource "vault_mount" "ssh_client" {
  path        = "ssh-client-signer"
  type        = "ssh"
  description = "Vault SSH CA issuing short-lived OpenSSH user certificates"
}

resource "vault_ssh_secret_backend_ca" "client_ca" {
  backend              = vault_mount.ssh_client.path
  generate_signing_key = true
  key_type             = "ed25519"
}

resource "vault_ssh_secret_backend_role" "admin_role" {
  backend                 = vault_mount.ssh_client.path
  name                    = "macprod-admin"
  key_type                = "ca"
  allow_user_certificates = true
  allow_user_key_ids      = true
  key_id_format           = "macprod-{{role_name}}-{{token_display_name}}"
  allowed_users           = "admin"
  default_user            = "admin"
  allowed_extensions      = "permit-pty,permit-port-forwarding,permit-agent-forwarding"
  default_extensions = {
    "permit-pty"             = ""
    "permit-port-forwarding" = ""
  }
  ttl     = "3600"
  max_ttl = "28800"
  depends_on = [vault_ssh_secret_backend_ca.client_ca]
}

resource "vault_policy" "ssh_client_sign" {
  name   = "ssh-client-sign"
  policy = <<-EOT
    path "ssh-client-signer/sign/macprod-admin" {
      capabilities = ["create", "update"]
    }
    path "ssh-client-signer/config/ca" {
      capabilities = ["read"]
    }
  EOT
}
