output "vm_ips" {
  description = "DHCP IPv4 addresses assigned to all Tart VMs"
  value       = local.vm_ips
}

output "ops_ip" {
  description = "External infra / HAProxy / Gitea / Zot / SeaweedFS / Vault node IP"
  value       = local.ops_ip
}

output "ssh_private_key" {
  description = "Path to generated SSH private key"
  value       = local.ssh_key_path
}
