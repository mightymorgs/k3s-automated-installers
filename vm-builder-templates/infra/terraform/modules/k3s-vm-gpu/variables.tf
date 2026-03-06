variable "libvirt_uri" {
  description = "Libvirt connection URI (e.g., qemu:///system)"
  type        = string
  default     = "qemu:///system"
}

variable "name" {
  description = "VM name (will be used for hostname and libvirt domain name)"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.name))
    error_message = "VM name must be a valid hostname (lowercase alphanumeric and hyphens, max 63 chars)."
  }
}

variable "vcpu" {
  description = "Number of virtual CPUs to allocate to the VM"
  type        = number
  default     = 2

  validation {
    condition     = var.vcpu >= 1 && var.vcpu <= 64
    error_message = "vCPU count must be between 1 and 64."
  }
}

variable "memory_mb" {
  description = "Amount of RAM in megabytes (e.g., 2048 for 2GB)"
  type        = number
  default     = 2048

  validation {
    condition     = var.memory_mb >= 512
    error_message = "Memory must be at least 512MB."
  }
}

variable "disk_size_gb" {
  description = "Root disk size in gigabytes (must be >= base image size, typically 20GB+)"
  type        = number
  default     = 20

  validation {
    condition     = var.disk_size_gb >= 10
    error_message = "Root disk size must be at least 10GB."
  }
}

variable "data_disk_size_gb" {
  description = "Optional data disk size in gigabytes (0 = no data disk)"
  type        = number
  default     = 0

  validation {
    condition     = var.data_disk_size_gb >= 0
    error_message = "Data disk size must be non-negative."
  }
}

variable "base_image_path" {
  description = "Absolute path to the base cloud image (qcow2 format, e.g., /var/lib/libvirt/images/ubuntu-24.04.qcow2)"
  type        = string

  validation {
    condition     = can(regex("^/.*\\.(qcow2|img)$", var.base_image_path))
    error_message = "Base image path must be absolute and end with .qcow2 or .img."
  }
}

variable "network_name" {
  description = "Libvirt network name to attach the VM to (e.g., 'default', 'bridge0')"
  type        = string
  default     = "default"
}

variable "mac" {
  description = "MAC address for the network interface (leave null for auto-assignment). Format: xx:xx:xx:xx:xx:xx"
  type        = string
  default     = null

  validation {
    condition     = var.mac == null || can(regex("^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", var.mac))
    error_message = "MAC address must be in format xx:xx:xx:xx:xx:xx (hexadecimal)."
  }
}
variable "ssh_authorized_keys" {
  description = "List of SSH public keys for authentication"
  type        = list(string)
}

variable "console_authorized_key" {
  description = "Optional SSH key to place in root's authorized_keys for console access"
  type        = string
  default     = ""
}

# ==============================================================================
# Console Access Configuration (for QEMU VM viewer fallback)
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

variable "enable_console_pw" {
  description = "Enable password authentication for console access (default: false for security)"
  type        = bool
  default     = false
}

variable "static_ipv4_cidr" {
  description = "Static IPv4 with CIDR (e.g., 192.168.0.28/24). Leave empty for DHCP."
  type        = string
  default     = ""
}

variable "gateway_ipv4" {
  description = "Gateway IPv4 when using static addressing"
  type        = string
  default     = ""
}

variable "dns_servers" {
  description = "DNS servers list for static addressing"
  type        = list(string)
  default     = []
}

variable "tailscale_tag" {
  description = "Tailscale tag to apply to this VM (e.g., tag:k8s-staging, tag:vm-host)"
  type        = string
  default     = ""
}

variable "tailscale_auth_key" {
  description = "Pre-generated Tailscale auth key (ephemeral) for cloud-init auto-join"
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_runner_labels" {
  description = "Labels for GitHub Actions runner (comma-separated)"
  type        = string
  default     = "self-hosted,libvirt"
}

variable "github_runner_version" {
  description = "GitHub Actions runner version to install"
  type        = string
  default     = "2.329.0"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.github_runner_version))
    error_message = "GitHub runner version must be in semver format (e.g., 2.329.0)"
  }
}

variable "enable_github_runner" {
  description = "Install GitHub Actions self-hosted runner via cloud-init"
  type        = bool
  default     = true
}

variable "runner_token" {
  description = "GitHub Actions runner registration token (ephemeral, 1h expiry) - generated by workflow"
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
  description = "GitHub repository for runner registration (format: owner/repo). Passed from workflow via github.repository."
  type        = string
  default     = ""
}

variable "enable_tailscale_setup" {
  description = "Run Ansible tailscale-setup playbook after VM creation"
  type        = bool
  default     = false
}

variable "ansible_user" {
  description = "SSH user for Ansible provisioning (defaults to ubuntu)"
  type        = string
  default     = "ubuntu"
}

variable "admin_user" {
  description = "Admin username for VM (in addition to ubuntu user)"
  type        = string
  default     = ""

  validation {
    condition     = var.admin_user == "" || can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.admin_user))
    error_message = "Admin username must be a valid Linux username (lowercase, alphanumeric, underscore, hyphen, max 32 chars)."
  }
}

variable "admin_password" {
  description = "Password for admin user (required if admin_user is set, min 12 characters recommended)"
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.admin_password == "" || length(var.admin_password) >= 12
    error_message = "Admin password must be at least 12 characters long when provided."
  }
}

# ==============================================================================
# UEFI/OVMF Firmware Configuration
# ==============================================================================

variable "firmware_path" {
  description = <<-EOD
    Path to UEFI firmware file (OVMF_CODE). Different distributions use different paths:
    - Debian/Ubuntu: /usr/share/OVMF/OVMF_CODE_4M.fd
    - Fedora/RHEL: /usr/share/edk2/ovmf/OVMF_CODE.fd
    - Arch Linux: /usr/share/ovmf/x64/OVMF_CODE.fd
    Set to empty string to use legacy BIOS boot instead of UEFI.
  EOD
  type        = string
  default     = "/usr/share/OVMF/OVMF_CODE_4M.fd"

  validation {
    condition     = var.firmware_path == "" || can(regex("^/.*\\.fd$", var.firmware_path))
    error_message = "Firmware path must be absolute and end with .fd, or empty for BIOS boot."
  }
}

variable "nvram_template_path" {
  description = <<-EOD
    Path to NVRAM template file (OVMF_VARS). Different distributions use different paths:
    - Debian/Ubuntu: /usr/share/OVMF/OVMF_VARS_4M.fd
    - Fedora/RHEL: /usr/share/edk2/ovmf/OVMF_VARS.fd
    - Arch Linux: /usr/share/ovmf/x64/OVMF_VARS.fd
    Only used when firmware_path is set (UEFI boot).
  EOD
  type        = string
  default     = "/usr/share/OVMF/OVMF_VARS_4M.fd"

  validation {
    condition     = var.nvram_template_path == "" || can(regex("^/.*\\.fd$", var.nvram_template_path))
    error_message = "NVRAM template path must be absolute and end with .fd."
  }
}

variable "nvram_path" {
  description = "Directory where per-VM NVRAM files will be stored (only used for UEFI boot)"
  type        = string
  default     = "/var/lib/libvirt/qemu/nvram"

  validation {
    condition     = can(regex("^/", var.nvram_path))
    error_message = "NVRAM path must be an absolute path."
  }
}

# ==============================================================================
# GPU Passthrough Configuration
# ==============================================================================

variable "enable_gpu_passthrough" {
  description = "Enable NVIDIA GPU PCI passthrough (requires GPU bound to VFIO driver on host)"
  type        = bool
  default     = false
}

variable "gpu_pci_address" {
  description = <<-EOD
    PCI address of GPU in format BB:DD.F (e.g., 01:00.0)
    - BB = Bus (2-digit hex)
    - DD = Device/Slot (2-digit hex)
    - F = Function (1-digit hex)
    Use 'lspci -nn | grep -i nvidia' to find your GPU's address.
    Both function 0 (GPU) and function 1 (audio) will be passed through.
  EOD
  type        = string
  default     = ""

  validation {
    condition     = var.gpu_pci_address == "" || can(regex("^[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\\.[0-9a-fA-F]$", var.gpu_pci_address))
    error_message = "GPU PCI address must be in format BB:DD.F (e.g., 01:00.0)."
  }
}

# ==============================================================================
# USB 5GbE NIC Passthrough Configuration
# ==============================================================================

variable "enable_usb_nic_passthrough" {
  description = <<-EOD
    Enable USB 5GbE NIC passthrough (passes entire USB device to VM)
    Use 'lsusb' to find vendor and product IDs.
    Example output: 'Bus 003 Device 004: ID 0b95:1790 ASIX Electronics Corp. AX88179 Gigabit Ethernet'
    - Vendor ID: 0b95
    - Product ID: 1790
  EOD
  type        = bool
  default     = false
}

variable "usb_nic_vendor_id" {
  description = "USB NIC vendor ID from lsusb (4-digit hex, e.g., 0b95 for ASIX)"
  type        = string
  default     = ""

  validation {
    condition     = var.usb_nic_vendor_id == "" || can(regex("^[0-9a-fA-F]{4}$", var.usb_nic_vendor_id))
    error_message = "USB NIC vendor ID must be 4-digit hex (e.g., 0b95)."
  }
}

variable "usb_nic_product_id" {
  description = "USB NIC product ID from lsusb (4-digit hex, e.g., 1790 for AX88179)"
  type        = string
  default     = ""

  validation {
    condition     = var.usb_nic_product_id == "" || can(regex("^[0-9a-fA-F]{4}$", var.usb_nic_product_id))
    error_message = "USB NIC product ID must be 4-digit hex (e.g., 1790)."
  }
}

variable "usb_nic_static_ip" {
  description = "Static IP address for USB NIC interface (e.g., 192.168.0.30). Leave empty for no USB NIC configuration."
  type        = string
  default     = ""
}

variable "usb_nic_gateway" {
  description = "Gateway IP for USB NIC network (e.g., 192.168.0.1). Only used if usb_nic_static_ip is set."
  type        = string
  default     = "192.168.0.1"
}

# ==============================================================================
# Pre-rendered Cloud-Init (J2 Template Integration)
# ==============================================================================

variable "user_data_content_b64" {
  description = <<-EOD
    Pre-rendered cloud-init user-data content from Jinja2 templates (BASE64 ENCODED).
    When provided (non-empty), this takes precedence over all internally
    generated cloud-init configurations.

    Must be BASE64 encoded to avoid shell variable interpolation issues when
    passing through environment variables (cloud-init contains $VARIABLES).

    Usage: Workflow renders ansible/templates/cloud-init/libvirt-userdata.yml.j2
    and passes the base64-encoded result via this variable.

    When empty (default), the module uses its internal cloud-init templates.
  EOD
  type        = string
  default     = ""
  sensitive   = false
}
