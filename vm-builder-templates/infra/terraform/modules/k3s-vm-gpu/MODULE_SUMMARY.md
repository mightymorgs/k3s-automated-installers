# K3s VM GPU Passthrough Module - Implementation Summary

**Created**: 2025-10-26
**Location**: `/home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu/`
**Status**: ✅ Complete and validated

## Overview

Complete Terraform module for deploying K3s VMs on libvirt with optional NVIDIA GPU and USB 5GbE NIC passthrough support. Adapted from AusterIT_Fresh base module with GPU/USB passthrough enhancements.

## Files Created

```
k3s-vm-gpu/
├── main.tf                     # Main resource definitions (510 lines)
├── variables.tf                # Input variables with validation (271 lines)
├── outputs.tf                  # Output values (38 lines)
├── cloudinit-cdrom-sata.xsl   # UEFI cloud-init fix (27 lines)
├── terraform.tfvars.example    # Example configuration (117 lines)
├── README.md                   # Complete documentation (501 lines)
└── MODULE_SUMMARY.md           # This file
```

**Total**: 6 files, ~1,464 lines of code/documentation

## Module Structure

### Base Foundation (Adapted)
**Source**: `/home/morgs/GitRepo/AusterIT_Fresh/infra/terraform/modules/libvirt-k3s-vm/`

**Preserved Components** (100% compatible):
- ✅ Cloud-init user-data structure
- ✅ Netplan static/DHCP configuration
- ✅ UEFI boot with OVMF firmware
- ✅ SATA cloud-init XSLT transformation (`cloudinit-cdrom-sata.xsl`)
- ✅ Tailscale Ansible integration
- ✅ Volume management (base, root, data disks)
- ✅ Network interface configuration
- ✅ Console and graphics setup
- ✅ Variable validation patterns
- ✅ Output structure

### New Enhancements

#### 1. GPU Passthrough (NVIDIA)
**Reference**: `/home/morgs/GitRepo/To Ingest/05-Applications/Edge-Use-Cases/KubeHomeAutomation/scripts/04-create-media-vm-with-gpu.sh`

**Implementation**:
- `null_resource.gpu_passthrough` - Post-creation virsh attach-device
- Passes both GPU functions (VGA + audio) automatically
- PCI address parsing logic (converts `01:00.0` → bus/slot/function)
- Conditional NVIDIA driver installation in cloud-init
- Validation: GPU address format and requirement checks

**Files Modified**:
- `main.tf`: Added locals for PCI parsing, null_resource for GPU attach
- `variables.tf`: Added `enable_gpu_passthrough`, `gpu_pci_address`
- `outputs.tf`: Added GPU status outputs

#### 2. USB NIC Passthrough (5GbE)
**Implementation**:
- `null_resource.usb_nic_passthrough` - Post-creation virsh attach-device
- Vendor/product ID-based device selection (stable across reboots)
- Sequential dependency after GPU passthrough
- Validation: 4-digit hex format for vendor/product IDs

**Files Modified**:
- `main.tf`: Added null_resource for USB attach
- `variables.tf`: Added `enable_usb_nic_passthrough`, `usb_nic_vendor_id`, `usb_nic_product_id`
- `outputs.tf`: Added USB NIC status outputs

#### 3. Enhanced Documentation
**New Files**:
- `README.md`: Complete usage guide (501 lines)
- `terraform.tfvars.example`: Example configurations (117 lines)
- `MODULE_SUMMARY.md`: This implementation summary

## Technical Implementation Details

### PCI Passthrough Pattern

**Challenge**: Libvirt Terraform provider doesn't support `hostdev` blocks natively.

**Solution**: Use `null_resource` with `virsh attach-device --config` to modify VM XML post-creation.

**Workflow**:
1. Terraform creates base VM (no GPU/USB attached)
2. `null_resource.gpu_passthrough` runs (if enabled):
   - Generates temporary GPU XML files (function 0 + function 1)
   - Shuts down VM
   - Attaches GPU via `virsh attach-device --config`
   - Starts VM
3. `null_resource.usb_nic_passthrough` runs (if enabled):
   - Generates temporary USB XML file
   - Shuts down VM (if not already down)
   - Attaches USB NIC via `virsh attach-device --config`
   - Starts VM

**Benefits**:
- Persistent configuration (--config flag)
- Survives VM reboots
- Compatible with Terraform state management
- Triggers on PCI address or USB ID changes

### PCI Address Parsing

**Input Format**: `01:00.0` (from lspci)
**Parsed to**:
```hcl
local.gpu_bus  = "0x01"  # Bus
local.gpu_slot = "0x00"  # Device/Slot
local.gpu_func = "0x0"   # Function
```

**XML Generation**:
```xml
<hostdev mode='subsystem' type='pci' managed='yes'>
  <source>
    <address domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>
  </source>
  <address type='pci' multifunction='on'/>
</hostdev>
```

### Dual GPU Functions

NVIDIA GPUs require two PCI functions:
- **Function 0** (`01:00.0`): VGA controller (primary GPU)
- **Function 1** (`01:00.1`): Audio controller (HDMI/DP audio)

Module automatically passes both when `enable_gpu_passthrough = true`.

### USB Device Selection

**USB passthrough uses vendor:product ID matching** (not bus/device numbers):
- More stable than bus/device (survives reboots/port changes)
- Detected via `lsusb` on host
- Example: `0b95:1790` (ASIX AX88179 5GbE adapter)

**XML Generation**:
```xml
<hostdev mode='subsystem' type='usb' managed='yes'>
  <source>
    <vendor id='0x0b95'/>
    <product id='0x1790'/>
  </source>
</hostdev>
```

## Variables Summary

### New Variables (GPU Passthrough)
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_gpu_passthrough` | bool | false | Enable GPU PCI passthrough |
| `gpu_pci_address` | string | "" | GPU address (e.g., "01:00.0") |

### New Variables (USB NIC Passthrough)
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_usb_nic_passthrough` | bool | false | Enable USB NIC passthrough |
| `usb_nic_vendor_id` | string | "" | USB vendor ID (4-digit hex) |
| `usb_nic_product_id` | string | "" | USB product ID (4-digit hex) |

### Inherited Variables (from base module)
- **VM Config**: name, vcpu, memory_mb, disk_size_gb, data_disk_size_gb
- **Networking**: static_ipv4_cidr, gateway_ipv4, dns_servers, mac
- **Authentication**: ssh_authorized_key, admin_user, admin_password
- **Tailscale**: enable_tailscale_setup, tailscale_tag
- **UEFI**: firmware_path, nvram_template_path, nvram_path

## Outputs Summary

### New Outputs
| Output | Description |
|--------|-------------|
| `gpu_passthrough_enabled` | GPU passthrough status (bool) |
| `gpu_pci_address` | GPU PCI address (if enabled) |
| `usb_nic_passthrough_enabled` | USB NIC passthrough status (bool) |
| `usb_nic_ids` | USB vendor:product IDs (if enabled) |

### Inherited Outputs
- `name`: VM hostname
- `ip_address`: Static IP (null if DHCP)
- `vcpu`: vCPU count
- `memory_mb`: Memory in MB
- `domain_id`: Libvirt domain ID

## Cloud-init Enhancements

### Standard Packages (Always)
- qemu-guest-agent
- curl
- gnupg

### GPU Packages (When `enable_gpu_passthrough = true`)
```yaml
packages:
  - nvidia-driver-535
  - nvidia-container-toolkit
```

Conditional installation via cloud-init template:
```hcl
%{if var.enable_gpu_passthrough~}
  - nvidia-driver-535
  - nvidia-container-toolkit
%{endif~}
```

## Validation and Safety

### Terraform Lifecycle Preconditions
1. **Admin user**: If `admin_user` set → `admin_password` required
2. **GPU passthrough**: If `enable_gpu_passthrough = true` → `gpu_pci_address` required
3. **USB NIC passthrough**: If `enable_usb_nic_passthrough = true` → both IDs required

### Variable Validations
- **VM name**: Valid hostname regex
- **vCPU**: 1-64 range
- **Memory**: Min 512MB
- **Disk size**: Min 10GB
- **MAC address**: xx:xx:xx:xx:xx:xx format
- **GPU PCI address**: BB:DD.F format (e.g., 01:00.0)
- **USB vendor/product IDs**: 4-digit hex format

### Terraform Validation Status
```bash
$ terraform validate
Success! The configuration is valid.
```

## Runtime Detection Requirements

### GPU PCI Address Detection
```bash
# On gaming laptop host:
lspci -nn | grep -i nvidia
# Example output:
# 01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA104M [GeForce RTX 3080 Mobile] [10de:249d]
# 01:00.1 Audio device [0403]: NVIDIA Corporation GA104 High Definition Audio Controller [10de:228b]

# Use first address: 01:00.0
```

### Verify VFIO Binding
```bash
lspci -k -s 01:00.0 | grep driver
# Should show: Kernel driver in use: vfio-pci
```

### USB NIC ID Detection
```bash
# On gaming laptop host:
lsusb | grep -i ethernet
# Example output:
# Bus 003 Device 004: ID 0b95:1790 ASIX Electronics Corp. AX88179 Gigabit Ethernet
#                        ^^^^ ^^^^
#                      vendor product

# Use in terraform.tfvars:
usb_nic_vendor_id  = "0b95"
usb_nic_product_id = "1790"
```

**Important**: These hardware IDs **cannot be hardcoded** - they must be detected at deployment time.

## Usage Example (Gaming Laptop)

```hcl
module "k3s_gpu_vm" {
  source = "../../modules/k3s-vm-gpu"

  name              = "k3s-gaming-laptop"
  vcpu              = 12
  memory_mb         = 29696  # 29GB
  disk_size_gb      = 500
  data_disk_size_gb = 1000
  base_image_path   = "/var/lib/libvirt/images/ubuntu-24.04.qcow2"

  # GPU Passthrough
  enable_gpu_passthrough = true
  gpu_pci_address       = "01:00.0"  # RTX 3080 Mobile

  # USB 5GbE NIC Passthrough
  enable_usb_nic_passthrough = true
  usb_nic_vendor_id         = "0b95"  # ASIX Electronics
  usb_nic_product_id        = "1790"  # AX88179 5GbE

  # Network
  static_ipv4_cidr  = "192.168.1.102/24"
  gateway_ipv4      = "192.168.1.1"
  dns_servers       = ["1.1.1.1", "8.8.8.8"]

  ssh_authorized_key = file("~/.ssh/id_rsa.pub")
}
```

## Differences from Base Module

### What's Exactly the Same
- ✅ All base variables (names, types, defaults, validations)
- ✅ All base cloud-init structure
- ✅ UEFI boot configuration
- ✅ Network configuration logic
- ✅ Tailscale integration pattern
- ✅ Volume management
- ✅ XSLT transformation for cloud-init SATA fix

### What's New/Different
- ➕ GPU passthrough via null_resource
- ➕ USB NIC passthrough via null_resource
- ➕ PCI address parsing logic
- ➕ Conditional NVIDIA driver installation
- ➕ 5 new variables (GPU + USB config)
- ➕ 4 new outputs (GPU + USB status)
- ➕ Enhanced README documentation
- ➕ terraform.tfvars.example with detection commands

### Lines of Code Changed
- `main.tf`: +146 lines (GPU/USB null_resources, PCI parsing)
- `variables.tf`: +64 lines (GPU/USB variables)
- `outputs.tf`: +28 lines (GPU/USB outputs)
- `cloudinit-cdrom-sata.xsl`: Unchanged (copied as-is)

**Total new code**: ~238 lines
**Total documentation**: ~618 lines (README + example + summary)

## Testing and Deployment

### Terraform Validation
```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu
terraform init
terraform validate
# ✅ Success! The configuration is valid.
```

### Next Steps (Manual Testing)
1. **Detect hardware on gaming laptop**:
   - Run `lspci -nn | grep -i nvidia` → Get GPU PCI address
   - Verify VFIO binding: `lspci -k -s 01:00.0 | grep driver`
   - Run `lsusb | grep -i ethernet` → Get USB NIC IDs

2. **Create terraform.tfvars** (copy from example, update with detected IDs)

3. **Test deployment**:
   ```bash
   terraform plan
   terraform apply
   ```

4. **Verify in VM**:
   ```bash
   ssh ubuntu@<vm-ip>
   lspci | grep -i nvidia      # Should show GPU
   nvidia-smi                   # Should show GPU stats
   lsusb                        # Should show USB NIC
   ip link show                 # Should show USB NIC interface
   ```

## Known Limitations

### Libvirt Provider Constraints
- **No native hostdev support**: Must use virsh attach-device
- **Requires VM shutdown**: Cannot hot-add PCI/USB devices
- **Post-creation only**: GPU/USB attached after initial VM creation

### Workarounds Implemented
- ✅ Use `null_resource` with local-exec provisioner
- ✅ Generate temporary XML files for virsh
- ✅ Use `--config` flag for persistent attachment
- ✅ Trigger on PCI/USB ID changes for idempotency

### Future Enhancements (Not Implemented)
- ⏳ Hot-plug support (requires QEMU guest agent coordination)
- ⏳ Multiple GPU support (currently single GPU)
- ⏳ USB device auto-detection (currently manual ID entry)
- ⏳ PCI device validation (check VFIO binding before attach)

## References

### Base Module
- **Path**: `/home/morgs/GitRepo/AusterIT_Fresh/infra/terraform/modules/libvirt-k3s-vm/`
- **Files**: main.tf, variables.tf, outputs.tf, cloudinit-cdrom-sata.xsl

### GPU Passthrough Pattern
- **Path**: `/home/morgs/GitRepo/To Ingest/05-Applications/Edge-Use-Cases/KubeHomeAutomation/scripts/04-create-media-vm-with-gpu.sh`
- **Key Lines**: 137-138 (--hostdev 01:00.0 with multifunction=on)

### K3s Target Deployment
- **Gaming Laptop**: RTX 3080 Mobile (01:00.0)
- **USB NIC**: ASIX AX88179 5GbE (typical ID: 0b95:1790)
- **Target Use**: K3s node with GPU for ML/AI workloads

## Integration with ansible-neo4j-memory Project

This module is part of the larger ansible-neo4j-memory project infrastructure:

**Project Context**:
- **Self-learning infrastructure automation platform**
- **Neo4j GraphRAG** for cluster observation and IaC generation
- **K3s deployment patterns** for ML/AI workloads

**Module Role**:
- Deploy K3s nodes with GPU support for Neo4j + BGE-M3 embeddings
- Enable ML workloads (NVIDIA container toolkit included)
- Support hybrid edge deployments (gaming laptop as K3s node)

**Future Integration**:
- Ansible playbooks will use this module via Terraform
- Discovery playbooks will observe these GPU-enabled VMs
- Pattern detection for GPU-accelerated deployments

## Conclusion

✅ **Module Status**: Complete and validated
✅ **Terraform Validation**: Passed
✅ **Documentation**: Comprehensive (README + examples + summary)
✅ **Base Compatibility**: 100% preserved from AusterIT_Fresh module
✅ **GPU Passthrough**: Implemented via virsh attach-device
✅ **USB NIC Passthrough**: Implemented via virsh attach-device
✅ **Ready for Deployment**: Yes (pending hardware ID detection)

**Next Action**: Deploy to gaming laptop with detected GPU/USB IDs and test K3s + GPU workloads.
