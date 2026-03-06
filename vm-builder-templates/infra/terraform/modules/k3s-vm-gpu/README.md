# K3s VM with GPU/USB NIC Passthrough Terraform Module

Terraform module for deploying K3s VMs on libvirt with optional NVIDIA GPU and USB 5GbE NIC passthrough support.

## Features

- **Base K3s VM**: Full-featured Ubuntu cloud-init VM deployment
- **GPU Passthrough**: NVIDIA GPU PCI passthrough (both function 0 and 1)
- **USB NIC Passthrough**: USB 5GbE network adapter passthrough
- **UEFI Boot**: Native UEFI/OVMF support with SATA cloud-init fix
- **Automated Setup**: Tailscale integration via Ansible
- **Flexible Networking**: Static IP or DHCP, MAC address control
- **Cloud-init**: Automated user setup, package installation, SSH keys

## Architecture

### Base Module
Adapted from `/home/morgs/GitRepo/AusterIT_Fresh/infra/terraform/modules/libvirt-k3s-vm/`

### GPU Passthrough Pattern
Based on `/home/morgs/GitRepo/To Ingest/05-Applications/Edge-Use-Cases/KubeHomeAutomation/scripts/04-create-media-vm-with-gpu.sh`

### Key Enhancements
1. **Dynamic hostdev blocks**: GPU and USB NIC passthrough are optional via boolean flags
2. **PCI address parsing**: Automatic conversion from `01:00.0` format to libvirt XML
3. **Dual GPU functions**: Passes both GPU (function 0) and GPU audio (function 1)
4. **USB device selection**: Vendor/product ID-based USB device passthrough
5. **NVIDIA driver automation**: Installs nvidia-driver-535 and nvidia-container-toolkit when GPU enabled

## Prerequisites

### Host Requirements

**GPU Passthrough**:
```bash
# Verify GPU is bound to VFIO driver
lspci -k -s 01:00.0 | grep -i driver
# Should show: Kernel driver in use: vfio-pci

# Find your GPU PCI address
lspci -nn | grep -i nvidia
# Example output: 01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA104M [GeForce RTX 3080 Mobile / Max-Q 8GB/16GB] [10de:249d] (rev a1)
#                 01:00.1 Audio device [0403]: NVIDIA Corporation GA104 High Definition Audio Controller [10de:228b] (rev a1)
# Use first address: 01:00.0
```

**USB NIC Passthrough**:
```bash
# Find USB NIC vendor/product IDs
lsusb
# Example output: Bus 003 Device 004: ID 0b95:1790 ASIX Electronics Corp. AX88179 Gigabit Ethernet
# Vendor ID: 0b95
# Product ID: 1790
```

**UEFI Firmware** (Ubuntu/Debian):
```bash
sudo apt install ovmf
ls /usr/share/OVMF/OVMF_CODE_4M.fd  # Should exist
```

## Usage

### Basic K3s VM (No Passthrough)

```hcl
module "k3s_vm" {
  source = "../../modules/k3s-vm-gpu"

  name              = "k3s-node-01"
  vcpu              = 4
  memory_mb         = 8192
  disk_size_gb      = 100
  base_image_path   = "/var/lib/libvirt/images/ubuntu-24.04.qcow2"

  static_ipv4_cidr  = "192.168.1.100/24"
  gateway_ipv4      = "192.168.1.1"
  dns_servers       = ["1.1.1.1", "8.8.8.8"]

  ssh_authorized_key = file("~/.ssh/id_rsa.pub")
}
```

### K3s VM with GPU Passthrough

```hcl
module "k3s_vm_gpu" {
  source = "../../modules/k3s-vm-gpu"

  name              = "k3s-gpu-node"
  vcpu              = 12
  memory_mb         = 29696  # 29GB
  disk_size_gb      = 500
  data_disk_size_gb = 1000   # Extra disk for container images
  base_image_path   = "/var/lib/libvirt/images/ubuntu-24.04.qcow2"

  # GPU Passthrough
  enable_gpu_passthrough = true
  gpu_pci_address       = "01:00.0"  # From lspci -nn | grep -i nvidia

  # Network
  static_ipv4_cidr  = "192.168.1.101/24"
  gateway_ipv4      = "192.168.1.1"
  dns_servers       = ["1.1.1.1", "8.8.8.8"]

  ssh_authorized_key = file("~/.ssh/id_rsa.pub")
}
```

### K3s VM with GPU + USB 5GbE NIC Passthrough

```hcl
module "k3s_vm_gpu_nic" {
  source = "../../modules/k3s-vm-gpu"

  name              = "k3s-gaming-laptop"
  vcpu              = 12
  memory_mb         = 29696
  disk_size_gb      = 500
  base_image_path   = "/var/lib/libvirt/images/ubuntu-24.04.qcow2"

  # GPU Passthrough
  enable_gpu_passthrough = true
  gpu_pci_address       = "01:00.0"

  # USB 5GbE NIC Passthrough
  enable_usb_nic_passthrough = true
  usb_nic_vendor_id         = "0b95"  # From lsusb
  usb_nic_product_id        = "1790"  # From lsusb

  # Network (will use passed-through USB NIC, but virtio NIC also available)
  static_ipv4_cidr  = "192.168.1.102/24"
  gateway_ipv4      = "192.168.1.1"
  dns_servers       = ["1.1.1.1", "8.8.8.8"]

  ssh_authorized_key = file("~/.ssh/id_rsa.pub")

  # Tailscale integration
  enable_tailscale_setup = true
  tailscale_tag         = "tag:k3s-gpu"
}
```

## Variables

### Core VM Configuration
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `name` | string | - | VM hostname (required) |
| `vcpu` | number | 2 | Number of vCPUs (1-64) |
| `memory_mb` | number | 2048 | RAM in megabytes (min 512) |
| `disk_size_gb` | number | 20 | Root disk size in GB (min 10) |
| `data_disk_size_gb` | number | 0 | Optional data disk size (0 = none) |
| `base_image_path` | string | - | Path to Ubuntu cloud image (required) |

### Networking
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `network_name` | string | "default" | Libvirt network name |
| `mac` | string | null | MAC address (auto if null) |
| `static_ipv4_cidr` | string | "" | Static IP with CIDR (empty = DHCP) |
| `gateway_ipv4` | string | "" | Gateway IP (for static) |
| `dns_servers` | list(string) | [] | DNS servers (for static) |

### GPU Passthrough
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_gpu_passthrough` | bool | false | Enable GPU PCI passthrough |
| `gpu_pci_address` | string | "" | GPU PCI address (e.g., "01:00.0") |

### USB NIC Passthrough
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_usb_nic_passthrough` | bool | false | Enable USB NIC passthrough |
| `usb_nic_vendor_id` | string | "" | USB vendor ID (4-digit hex) |
| `usb_nic_product_id` | string | "" | USB product ID (4-digit hex) |

### Authentication
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ssh_authorized_key` | string | - | SSH public key (required) |
| `admin_user` | string | "" | Additional admin user |
| `admin_password` | string | "" | Admin password (min 12 chars) |
| `enable_console_pw` | bool | false | Enable ubuntu user password |
| `console_password` | string | "" | Ubuntu user password |

### Tailscale Integration
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_tailscale_setup` | bool | false | Run Ansible Tailscale setup |
| `tailscale_tag` | string | "" | Tailscale tag (e.g., "tag:k3s") |
| `ansible_user` | string | "ubuntu" | SSH user for Ansible |

### UEFI Firmware
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `firmware_path` | string | "/usr/share/OVMF/OVMF_CODE_4M.fd" | UEFI firmware path |
| `nvram_template_path` | string | "/usr/share/OVMF/OVMF_VARS_4M.fd" | NVRAM template path |
| `nvram_path` | string | "/var/lib/libvirt/qemu/nvram" | NVRAM storage directory |

## Outputs

| Output | Description |
|--------|-------------|
| `name` | VM name |
| `ip_address` | Static IP (null if DHCP) |
| `vcpu` | vCPU count |
| `memory_mb` | Memory in MB |
| `gpu_passthrough_enabled` | GPU passthrough status |
| `gpu_pci_address` | GPU PCI address (if enabled) |
| `usb_nic_passthrough_enabled` | USB NIC passthrough status |
| `usb_nic_ids` | USB vendor:product IDs (if enabled) |
| `domain_id` | Libvirt domain ID |

## Implementation Notes

### What's Adapted from Base Module

**From** `/home/morgs/GitRepo/AusterIT_Fresh/infra/terraform/modules/libvirt-k3s-vm/`:

✅ **Preserved** (no changes):
- Cloud-init user-data structure
- Netplan static/DHCP configuration
- UEFI boot with OVMF firmware
- SATA cloud-init XSLT transformation
- Tailscale Ansible integration
- Volume management (base, root, data)
- Network interface configuration
- Console and graphics setup

### What's New in This Module

**Added GPU Passthrough** (from virt-install script pattern):
- Dynamic `hostdev` block for GPU function 0 (primary)
- Dynamic `hostdev` block for GPU function 1 (audio/HDMI)
- PCI address parsing logic (converts `01:00.0` to bus/slot/function)
- Conditional NVIDIA driver installation in cloud-init
- Validation: GPU address required if passthrough enabled

**Added USB NIC Passthrough**:
- Dynamic `hostdev` block for USB devices
- Vendor/product ID-based device selection
- Validation: Both vendor and product IDs required if enabled

**Enhanced Variables**:
- `enable_gpu_passthrough` (bool)
- `gpu_pci_address` (string with regex validation)
- `enable_usb_nic_passthrough` (bool)
- `usb_nic_vendor_id` (4-digit hex validation)
- `usb_nic_product_id` (4-digit hex validation)

**Enhanced Outputs**:
- GPU passthrough status and address
- USB NIC passthrough status and IDs

### Runtime Detection Requirements

**USB NIC vendor/product IDs** must be detected on the gaming laptop:

```bash
# On gaming laptop host:
lsusb | grep -i ethernet
# Example output: Bus 003 Device 004: ID 0b95:1790 ASIX Electronics Corp. AX88179 Gigabit Ethernet

# Use in terraform.tfvars:
usb_nic_vendor_id  = "0b95"
usb_nic_product_id = "1790"
```

**Note**: These IDs are hardware-specific and cannot be hardcoded. They must be detected at deployment time.

## GPU Passthrough Technical Details

### PCI Address Format

**Input**: `01:00.0` (lspci format)
**Parsed to**:
- Bus: `0x01`
- Slot: `0x00`
- Function: `0x0`

### Dual Function Passthrough

NVIDIA GPUs have two PCI functions:
- **Function 0** (`01:00.0`): Primary GPU (VGA controller)
- **Function 1** (`01:00.1`): GPU audio (HDMI/DP audio)

Both must be passed through together. The module automatically passes function 1 when GPU passthrough is enabled.

### multifunction=on

The first hostdev (function 0) has `multifunction=on` to indicate multiple functions share the same slot. This is required for proper GPU operation.

## USB NIC Passthrough Technical Details

### Device Selection

USB passthrough uses **vendor:product ID** matching (not bus/device numbers, which change):
- More stable than bus/device numbers
- Survives host reboots
- Works across USB port changes

### Network Redundancy

VM will have **two network interfaces** when USB NIC passthrough is enabled:
1. **virtio NIC**: Virtual network (virbr0 or bridge)
2. **USB 5GbE NIC**: Passed-through physical adapter

This provides:
- Fallback if USB NIC has issues
- Management network (virtio) vs production network (USB NIC)
- Testing/debugging flexibility

## Cloud-init Packages

### Standard Packages (Always Installed)
- `qemu-guest-agent`
- `curl`
- `gnupg`

### GPU Packages (When `enable_gpu_passthrough = true`)
- `nvidia-driver-535`
- `nvidia-container-toolkit`

## Validation and Safety

### Preconditions (Terraform Lifecycle)

1. **Admin user validation**: If `admin_user` set, `admin_password` required
2. **GPU validation**: If `enable_gpu_passthrough = true`, `gpu_pci_address` required
3. **USB NIC validation**: If `enable_usb_nic_passthrough = true`, both `usb_nic_vendor_id` and `usb_nic_product_id` required

### Variable Validations

- **VM name**: Valid hostname (lowercase, alphanumeric, hyphens, max 63 chars)
- **vCPU**: 1-64 range
- **Memory**: Min 512MB
- **Disk size**: Min 10GB
- **MAC address**: Valid format (xx:xx:xx:xx:xx:xx)
- **GPU PCI address**: Valid format (BB:DD.F)
- **USB IDs**: 4-digit hex format

## Troubleshooting

### GPU Not Working

```bash
# On host: Verify VFIO binding
lspci -k -s 01:00.0 | grep driver
# Should show: Kernel driver in use: vfio-pci

# On host: Check IOMMU groups
find /sys/kernel/iommu_groups/ -type l | grep 01:00

# In VM: Check GPU detection
lspci | grep -i nvidia
nvidia-smi
```

### USB NIC Not Appearing

```bash
# On host: Verify USB device exists
lsusb | grep 0b95:1790

# On host: Check if device is bound to vfio-pci
lsusb -t  # Shows device tree

# In VM: Check USB devices
lsusb
ip link show  # Should show USB NIC interface
```

### Cloud-init Not Running (UEFI)

The module includes XSLT transformation to fix UEFI cloud-init issues:
- Changes cloud-init CDROM from IDE to SATA bus
- Q35/UEFI machines don't detect IDE properly
- File: `cloudinit-cdrom-sata.xsl`

Verify:
```bash
# In VM: Check cloud-init status
cloud-init status
cat /var/log/cloud-init.log
```

## Files

```
k3s-vm-gpu/
├── main.tf                     # Main resource definitions
├── variables.tf                # Input variables
├── outputs.tf                  # Output values
├── cloudinit-cdrom-sata.xsl   # UEFI cloud-init fix
└── README.md                   # This file
```

## License

Adapted from AusterIT_Fresh libvirt-k3s-vm module.
GPU passthrough pattern from KubeHomeAutomation project.
