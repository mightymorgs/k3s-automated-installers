variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region (e.g., us-central1, europe-west1)"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone (e.g., us-central1-a)"
  type        = string
  default     = "us-central1-a"
}

variable "name" {
  description = "VM name (will be used for hostname)"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.name))
    error_message = "VM name must be a valid hostname (lowercase alphanumeric and hyphens, max 63 chars)."
  }
}

variable "machine_type" {
  description = "GCP machine type (e.g., e2-medium, e2-standard-2)"
  type        = string
  default     = "e2-medium" # 2 vCPU, 4GB RAM, ~$24/mo

  validation {
    condition     = can(regex("^(e2|n1|n2|n2d|c2|c2d|m1|m2|t2d|t2a)-(micro|small|medium|standard|highmem|highcpu)(-[0-9]+)?$", var.machine_type)) || can(regex("^(f1-micro|g1-small)$", var.machine_type))
    error_message = "Machine type must be a valid GCP instance type (e.g., e2-medium, e2-standard-2, n1-standard-1)."
  }
}

variable "boot_disk_image" {
  description = "Boot disk image (e.g., ubuntu-os-cloud/ubuntu-2404-lts-amd64)"
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-noble-amd64-v20241219"
}

variable "boot_disk_size_gb" {
  description = "Boot disk size in GB"
  type        = number
  default     = 20

  validation {
    condition     = var.boot_disk_size_gb >= 10 && var.boot_disk_size_gb <= 10000
    error_message = "Boot disk size must be between 10 and 10000 GB."
  }
}

variable "boot_disk_type" {
  description = "Boot disk type (pd-standard, pd-balanced, pd-ssd)"
  type        = string
  default     = "pd-balanced"

  validation {
    condition     = contains(["pd-standard", "pd-balanced", "pd-ssd"], var.boot_disk_type)
    error_message = "Boot disk type must be one of: pd-standard, pd-balanced, pd-ssd."
  }
}

variable "data_disk_size_gb" {
  description = "Optional data disk size in GB (0 = no data disk)"
  type        = number
  default     = 0

  validation {
    condition     = var.data_disk_size_gb >= 0 && var.data_disk_size_gb <= 10000
    error_message = "Data disk size must be between 0 and 10000 GB."
  }
}

variable "data_disk_type" {
  description = "Data disk type (pd-standard, pd-balanced, pd-ssd)"
  type        = string
  default     = "pd-standard"
}

variable "network_name" {
  description = "VPC network name"
  type        = string
  default     = "default"
}

variable "subnet_name" {
  description = "VPC subnet name"
  type        = string
  default     = "default"
}

variable "enable_external_ip" {
  description = "Assign external (public) IP address"
  type        = bool
  default     = true
}

variable "enable_static_ip" {
  description = "Reserve static external IP (persists across VM rebuilds)"
  type        = bool
  default     = false
}

variable "enable_ssh_firewall" {
  description = "Create firewall rule for SSH access"
  type        = bool
  default     = true
}

variable "ssh_source_ranges" {
  description = "Source IP ranges allowed for SSH (in addition to Tailscale CGNAT)"
  type        = list(string)
  default     = ["0.0.0.0/0"] # WARN: Open to internet, rely on SSH keys + Tailscale
}

variable "ssh_authorized_keys" {
  description = "List of SSH public keys for authentication"
  type        = list(string)
}

variable "static_ipv4_cidr" {
  description = "Static IPv4 with CIDR (e.g., 10.128.0.50/32). Leave empty for DHCP. Note: GCP provides external IP automatically."
  type        = string
  default     = ""
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
  default     = "2.331.0"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.github_runner_version))
    error_message = "GitHub runner version must be in semver format (e.g., 2.331.0)"
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

variable "service_account_email" {
  description = "Service account email for VM (default = Compute Engine default service account)"
  type        = string
  default     = null
}

variable "service_account_scopes" {
  description = "Service account scopes for GCP API access"
  type        = list(string)
  default     = ["cloud-platform"] # Full access (restrict in production)
}

variable "deletion_protection" {
  description = "Enable deletion protection (prevents accidental deletion)"
  type        = bool
  default     = false
}
