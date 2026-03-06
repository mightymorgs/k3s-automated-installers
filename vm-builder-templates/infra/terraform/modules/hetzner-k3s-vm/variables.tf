variable "name" {
  description = "VM name (will be used for hostname)"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.name))
    error_message = "VM name must be a valid hostname (lowercase alphanumeric and hyphens, max 63 chars)."
  }
}

variable "server_type" {
  description = "Hetzner Cloud server type (e.g., cx22, cpx11, ccx13)"
  type        = string
  default     = "cx22" # 2 vCPU, 4GB RAM, €4.15/mo

  validation {
    condition     = can(regex("^(cx|cpx|ccx)[0-9]{2,3}$", var.server_type))
    error_message = "Server type must be a valid Hetzner Cloud type (e.g., cx22, cpx11, ccx13)."
  }
}

variable "base_image" {
  description = "Hetzner Cloud base image (e.g., ubuntu-24.04, debian-12)"
  type        = string
  default     = "ubuntu-24.04"
}

variable "location" {
  description = "Hetzner datacenter location (nbg1, fsn1, hel1, ash, hil)"
  type        = string
  default     = "nbg1" # Nuremberg - cheapest

  validation {
    condition     = contains(["nbg1", "fsn1", "hel1", "ash", "hil"], var.location)
    error_message = "Location must be one of: nbg1, fsn1, hel1, ash, hil."
  }
}

variable "ssh_authorized_keys" {
  description = "List of SSH public keys for authentication"
  type        = list(string)
}

variable "static_ipv4_cidr" {
  description = "Static IPv4 with CIDR (e.g., 192.168.0.50/24). Leave empty for DHCP. Note: Hetzner provides public IPs automatically."
  type        = string
  default     = ""
}

variable "gateway_ipv4" {
  description = "Gateway IPv4 when using static addressing (only for private networks)"
  type        = string
  default     = ""
}

variable "dns_servers" {
  description = "DNS servers list for static addressing"
  type        = list(string)
  default     = ["1.1.1.1", "8.8.8.8"]
}

variable "purpose" {
  description = "Purpose/workload identifier (e.g., media_stack, platform)"
  type        = string
  default     = "k3s"
}

variable "runner_token" {
  description = "GitHub Actions runner registration token (ephemeral, 1h expiry)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "ssh_private_key_b64" {
  description = "Base64-encoded SSH private key for GitHub deploy key access"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository for runner registration (format: owner/repo)"
  type        = string
  default     = "mightymorgs/k8s-platform-automation"
}

variable "github_runner_version" {
  description = "GitHub Actions runner version to install"
  type        = string
  default     = "2.332.0"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.github_runner_version))
    error_message = "GitHub runner version must be in semver format (e.g., 2.332.0)"
  }
}

variable "bws_access_token" {
  description = "BWS access token for inventory management"
  type        = string
  sensitive   = true
  default     = ""
}

variable "inventory_key" {
  description = "BWS inventory key for this VM"
  type        = string
  default     = ""
}

# ==============================================================================
# Optional Features
# ==============================================================================

variable "enable_floating_ip" {
  description = "Allocate a static floating IP (persistent across server rebuilds)"
  type        = bool
  default     = false
}

variable "private_network_id" {
  description = "Hetzner private network ID to attach (null = no private network)"
  type        = number
  default     = null
}

variable "private_ip" {
  description = "Private IP address within the private network"
  type        = string
  default     = null
}

variable "data_volume_size_gb" {
  description = "Optional data volume size in gigabytes (0 = no data volume)"
  type        = number
  default     = 0

  validation {
    condition     = var.data_volume_size_gb >= 0 && var.data_volume_size_gb <= 10000
    error_message = "Data volume size must be between 0 and 10000 GB."
  }
}

variable "firewall_ids" {
  description = "List of Hetzner firewall IDs to apply (optional - Tailscale provides network security)"
  type        = list(number)
  default     = []
}

# ==============================================================================
# Console Access Configuration (for fallback access)
# Sourced from BWS: inventory/shared/secrets/console/*
# ==============================================================================

variable "console_username" {
  description = "Username for console/SSH access (sourced from BWS)"
  type        = string
  default     = ""
}

variable "console_password" {
  description = "Password for console user (sourced from BWS)"
  type        = string
  default     = ""
  sensitive   = true
}
