terraform {
  required_version = ">= 1.5.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.4"
    }
  }
}

locals {
  config        = yamldecode(file(var.cluster_config_path))
  project_root  = abspath("${path.module}/../../..")
  runtime_dir   = "${local.project_root}/.runtime"
  ssh_key_path  = pathexpand(local.config.ssh.private_key_path)
  nodes_by_name = { for n in local.config.nodes : n.name => n }
}

# 1. Dedicated SSH ed25519 keypair for Ansible & bastion operations
resource "null_resource" "ssh_keypair" {
  triggers = {
    key_path = local.ssh_key_path
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      mkdir -p "$(dirname "${local.ssh_key_path}")" "${local.runtime_dir}/vm-ips"
      if [ ! -f "${local.ssh_key_path}" ]; then
        ssh-keygen -t ed25519 -f "${local.ssh_key_path}" -N "" -C "${local.config.project}-automation" >/dev/null
      fi
      chmod 600 "${local.ssh_key_path}"
      chmod 644 "${local.ssh_key_path}.pub"
    EOT
  }
}

# 2. Ensure Tart base image exists locally
resource "null_resource" "base_image" {
  triggers = {
    base_image = local.config.base_image
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      if ! tart list | awk '{print $2}' | grep -qx "${local.config.base_image}"; then
        tart pull "${local.config.base_image}"
      fi
    EOT
  }
}

# 3. Clone and size Tart VMs (never colliding with existing non-macprod VMs)
resource "null_resource" "vm_clone" {
  for_each   = local.nodes_by_name
  depends_on = [null_resource.base_image, null_resource.ssh_keypair]

  triggers = {
    vm_name    = each.key
    base_image = local.config.base_image
    cpu        = tostring(each.value.cpu)
    memory     = tostring(each.value.memory)
    disk_gb    = tostring(each.value.disk_gb)
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      if ! tart list | awk '$1=="local"{print $2}' | grep -qx "${each.key}"; then
        tart clone "${local.config.base_image}" "${each.key}"
        tart set "${each.key}" --disk-size ${each.value.disk_gb}
      fi
      tart set "${each.key}" --cpu ${each.value.cpu} --memory ${each.value.memory}
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      tart stop "${self.triggers.vm_name}" 2>/dev/null || true
      sleep 2
      if tart list | awk '$1=="local"{print $2}' | grep -qx "${self.triggers.vm_name}"; then
        tart delete "${self.triggers.vm_name}"
      fi
    EOT
  }
}

# 4. Boot all VMs via Softnet allow-all & distribute SSH public key idempotently
resource "null_resource" "vm_boot_and_ssh" {
  for_each   = local.nodes_by_name
  depends_on = [null_resource.vm_clone]

  triggers = {
    vm_name      = each.key
    project_root = local.project_root
    ssh_key_path = local.ssh_key_path
    ssh_user     = local.config.ssh.user
    ssh_pass     = local.config.ssh.default_password
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      "${self.triggers.project_root}/scripts/ops-vm-ctl.sh" ensure-vm "${self.triggers.vm_name}" "${self.triggers.ssh_user}" "${self.triggers.ssh_pass}" "${self.triggers.ssh_key_path}"
    EOT
  }
}

# 5. Read assigned DHCP IPs after boot
data "local_file" "vm_ip" {
  for_each   = local.nodes_by_name
  depends_on = [null_resource.vm_boot_and_ssh]
  filename   = "${local.runtime_dir}/vm-ips/${each.key}.ip"
}

locals {
  vm_ips = { for k, f in data.local_file.vm_ip : k => trimspace(f.content) }

  ops_nodes = [for n in local.config.nodes : n if n.role == "ops"]
  cp_nodes  = [for n in local.config.nodes : n if n.role == "control_plane"]
  wk_nodes  = [for n in local.config.nodes : n if n.role == "worker"]
  ops_ip    = local.vm_ips[local.ops_nodes[0].name]
}

# 6. Render Ansible inventory & generated group_vars (SSOT -> Ansible)
resource "local_file" "ansible_inventory" {
  filename        = "${local.project_root}/infra/ansible/inventories/hosts.ini"
  file_permission = "0644"
  content = templatefile("${path.module}/templates/hosts.ini.tftpl", {
    ops_nodes    = local.ops_nodes
    cp_nodes     = local.cp_nodes
    wk_nodes     = local.wk_nodes
    vm_ips       = local.vm_ips
    ssh_user     = local.config.ssh.user
    ssh_key_path = local.ssh_key_path
  })
}

resource "local_file" "ansible_generated_vars" {
  filename        = "${local.project_root}/infra/ansible/inventories/generated.yml"
  file_permission = "0644"
  content = yamlencode({
    project_name     = local.config.project
    internal_domain  = local.config.domain
    ops_vm_name      = local.ops_nodes[0].name
    ops_ip           = local.ops_ip
    k8s_version      = local.config.kubernetes.version
    pod_cidr         = local.config.kubernetes.pod_cidr
    service_cidr     = local.config.kubernetes.service_cidr
    api_port         = local.config.kubernetes.api_port
    versions         = local.config.versions
    node_ips         = local.vm_ips
    control_planes   = [for n in local.cp_nodes : { name = n.name, ip = local.vm_ips[n.name], bootstrap = try(n.bootstrap, false) }]
    workers          = [for n in local.wk_nodes : { name = n.name, ip = local.vm_ips[n.name] }]
  })
}
