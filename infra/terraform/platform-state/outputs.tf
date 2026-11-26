output "vault_eso_role" {
  value = vault_kubernetes_auth_backend_role.eso_role.role_name
}

output "managed_namespaces" {
  value = keys(kubernetes_namespace.managed)
}

output "ssh_ca_mount" {
  value = vault_mount.ssh_client.path
}

output "ssh_ca_role" {
  value = vault_ssh_secret_backend_role.admin_role.name
}

output "ssh_ca_public_key" {
  value = vault_ssh_secret_backend_ca.client_ca.public_key
}
