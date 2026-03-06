terraform {
  required_version = ">= 1.5.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}

locals {
  # Extract IP from CIDR if provided (e.g., "192.168.0.50/24" -> "192.168.0.50")
  static_ip = var.static_ipv4_cidr != "" ? split("/", var.static_ipv4_cidr)[0] : null

  # Netplan configuration for static IP (used in cloud-init)
  # On Hetzner, the primary interface will be eth0 or ens3
  network_cfg_static = <<-YAML
    network:
      version: 2
      renderer: networkd
      ethernets:
        eth0:
          match:
            name: e*
          dhcp4: false
          addresses: [${var.static_ipv4_cidr}]
          routes:
            - to: default
              via: ${var.gateway_ipv4}
          nameservers:
            addresses: [${join(", ", var.dns_servers)}]
  YAML

  network_cfg_dhcp = <<-YAML
    network:
      version: 2
      renderer: networkd
      ethernets:
        eth0:
          match:
            name: e*
          dhcp4: true
  YAML

  # Choose static or DHCP network config
  netplan_file = var.static_ipv4_cidr != "" ? local.network_cfg_static : local.network_cfg_dhcp

  # Cloud-init user data
  # Uses the new bootstrap template pattern from libvirt module
  user_data_bootstrap = templatefile("${path.module}/templates/cloud-init-bootstrap.yaml.j2", {
    vm_name               = var.name
    ssh_private_key_b64   = var.ssh_private_key_b64
    runner_token          = var.runner_token
    github_repo           = var.github_repo
    github_runner_version = var.github_runner_version
    netplan_content       = local.netplan_file
    ssh_authorized_keys   = var.ssh_authorized_keys
    bws_access_token      = var.bws_access_token
    inventory_key         = var.inventory_key
    # Console access (sourced from BWS: inventory/shared/secrets/console/*)
    console_username      = var.console_username
    console_password      = var.console_password
  })
}

# SSH key for root access
resource "hcloud_ssh_key" "deploy" {
  name       = "${var.name}-key"
  public_key = var.ssh_authorized_keys[0]
}

# Hetzner Cloud server
resource "hcloud_server" "vm" {
  name        = var.name
  server_type = var.server_type
  image       = var.base_image
  location    = var.location

  # Cloud-init user data
  user_data = local.user_data_bootstrap

  # SSH key for initial access
  ssh_keys = [hcloud_ssh_key.deploy.id]

  # Labels for organization
  labels = {
    client     = split("-", var.name)[0] # Extract client from hostname
    purpose    = var.purpose
    managed_by = "terraform"
    project    = "k8s-platform-automation"
  }

  # Firewall rules (optional - Tailscale provides network security)
  # firewall_ids = var.firewall_ids

  lifecycle {
    precondition {
      condition     = var.runner_token != "" || var.ssh_authorized_keys != []
      error_message = "Either runner_token or ssh_authorized_keys must be provided."
    }
  }
}

# Optional: Floating IP for static public address
resource "hcloud_floating_ip" "public" {
  count         = var.enable_floating_ip ? 1 : 0
  type          = "ipv4"
  home_location = var.location
  name          = "${var.name}-public-ip"

  labels = {
    vm = var.name
  }
}

resource "hcloud_floating_ip_assignment" "public" {
  count          = var.enable_floating_ip ? 1 : 0
  floating_ip_id = hcloud_floating_ip.public[0].id
  server_id      = hcloud_server.vm.id
}

# Optional: Private network for inter-VM communication
resource "hcloud_server_network" "private" {
  count      = var.private_network_id != null ? 1 : 0
  server_id  = hcloud_server.vm.id
  network_id = var.private_network_id
  ip         = var.private_ip
}

# Optional: Additional volume for data storage
resource "hcloud_volume" "data" {
  count     = var.data_volume_size_gb > 0 ? 1 : 0
  name      = "${var.name}-data"
  size      = var.data_volume_size_gb
  location  = var.location
  format    = "ext4"

  labels = {
    vm = var.name
  }
}

resource "hcloud_volume_attachment" "data" {
  count     = var.data_volume_size_gb > 0 ? 1 : 0
  volume_id = hcloud_volume.data[0].id
  server_id = hcloud_server.vm.id
  automount = true
}
