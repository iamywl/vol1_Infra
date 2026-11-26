variable "vault_addr" {
  type = string
}

variable "vault_token" {
  type      = string
  sensitive = true
}

variable "kubeconfig_path" {
  type = string
}

variable "k8s_api_endpoint" {
  type = string
}

variable "k8s_ca_cert" {
  type = string
}

variable "vault_reviewer_jwt" {
  type      = string
  sensitive = true
}

variable "order_db_password" {
  type      = string
  sensitive = true
  default   = "OrderPgHa2026!"
}

variable "order_api_key" {
  type      = string
  sensitive = true
  default   = "macprod-secret-v1-token"
}

variable "s3_access_key" {
  type    = string
  default = "macprod-s3-admin"
}

variable "s3_secret_key" {
  type      = string
  sensitive = true
  default   = "macprod-s3-secret-2026"
}
