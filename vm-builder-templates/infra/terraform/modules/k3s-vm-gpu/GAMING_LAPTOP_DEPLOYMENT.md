# Gaming Laptop K3s VM Deployment Guide

**Target Hardware**: Gaming laptop with RTX 3080 Mobile + USB 5GbE NIC
**Purpose**: Deploy K3s VM with GPU passthrough for Neo4j + BGE-M3 embeddings
**Module**: `/home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu/`

---

## Prerequisites

### 1. Host Configuration

**Verify GPU bound to VFIO**:
```bash
lspci -k -s 01:00.0 | grep driver
# Expected: Kernel driver in use: vfio-pci

# If not bound to VFIO, see GPU passthrough setup guide
```

**Verify IOMMU enabled**:
```bash
dmesg | grep -i iommu
# Should show: IOMMU enabled
```

**Verify UEFI firmware installed**:
```bash
ls /usr/share/OVMF/OVMF_CODE_4M.fd
# Should exist
```

### 2. Download Ubuntu Cloud Image

```bash
cd /var/lib/libvirt/images
wget https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img
mv ubuntu-24.04-server-cloudimg-amd64.img ubuntu-24.04.qcow2
```

---

## Step 1: Detect Hardware IDs

### GPU PCI Address

```bash
lspci -nn | grep -i nvidia
```

**Expected Output**:
```
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA104M [GeForce RTX 3080 Mobile / Max-Q 8GB/16GB] [10de:249d] (rev a1)
01:00.1 Audio device [0403]: NVIDIA Corporation GA104 High Definition Audio Controller [10de:228b] (rev a1)
```

**Extract**: Use first address → `01:00.0`

### USB 5GbE NIC IDs

```bash
lsusb | grep -i ethernet
```

**Expected Output** (example for ASIX adapter):
```
Bus 003 Device 004: ID 0b95:1790 ASIX Electronics Corp. AX88179 Gigabit Ethernet
```

**Extract**:
- Vendor ID: `0b95`
- Product ID: `1790`

**Note**: Your USB NIC vendor/product IDs may differ. Use actual values from lsusb.

---

## Step 2: Create terraform.tfvars

```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu
cp terraform.tfvars.example terraform.tfvars
```

**Edit terraform.tfvars**:
```hcl
# Gaming Laptop K3s VM Configuration

# ==============================================================================
# BASIC VM CONFIGURATION
# ==============================================================================

name             = "k3s-gaming-laptop"
vcpu             = 12
memory_mb        = 29696  # 29GB (adjust based on host RAM)
disk_size_gb     = 500
data_disk_size_gb = 1000  # Extra disk for container images

base_image_path  = "/var/lib/libvirt/images/ubuntu-24.04.qcow2"

# ==============================================================================
# NETWORK CONFIGURATION
# ==============================================================================

network_name     = "default"
static_ipv4_cidr = "192.168.1.102/24"  # Adjust for your network
gateway_ipv4     = "192.168.1.1"
dns_servers      = ["1.1.1.1", "8.8.8.8"]

# ==============================================================================
# GPU PASSTHROUGH (RTX 3080 Mobile)
# ==============================================================================

enable_gpu_passthrough = true
gpu_pci_address       = "01:00.0"  # From: lspci -nn | grep -i nvidia

# ==============================================================================
# USB 5GbE NIC PASSTHROUGH
# ==============================================================================

enable_usb_nic_passthrough = true
usb_nic_vendor_id         = "0b95"  # From: lsusb | grep -i ethernet
usb_nic_product_id        = "1790"  # From: lsusb | grep -i ethernet

# ==============================================================================
# SSH AUTHENTICATION
# ==============================================================================

ssh_authorized_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC... <YOUR_SSH_KEY_HERE>"

# Optional: Additional admin user
# admin_user     = "morgan"
# admin_password = "YourSecurePassword123!"

# ==============================================================================
# TAILSCALE INTEGRATION (Optional)
# ==============================================================================

enable_tailscale_setup = true
tailscale_tag         = "tag:k3s-gpu"
ansible_user          = "ubuntu"

# ==============================================================================
# UEFI FIRMWARE (Ubuntu defaults)
# ==============================================================================

firmware_path        = "/usr/share/OVMF/OVMF_CODE_4M.fd"
nvram_template_path  = "/usr/share/OVMF/OVMF_VARS_4M.fd"
nvram_path           = "/var/lib/libvirt/qemu/nvram"
```

**Important**: Replace `<YOUR_SSH_KEY_HERE>` with your actual SSH public key:
```bash
cat ~/.ssh/id_rsa.pub
```

---

## Step 3: Create Terraform Configuration

Create a deployment directory:
```bash
mkdir -p /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/deployments/gaming-laptop
cd /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/deployments/gaming-laptop
```

**Create main.tf**:
```hcl
terraform {
  required_version = ">= 1.5.0"
}

provider "libvirt" {
  uri = "qemu:///system"
}

module "k3s_gpu_vm" {
  source = "../../modules/k3s-vm-gpu"

  # Load variables from terraform.tfvars
  name              = var.name
  vcpu              = var.vcpu
  memory_mb         = var.memory_mb
  disk_size_gb      = var.disk_size_gb
  data_disk_size_gb = var.data_disk_size_gb
  base_image_path   = var.base_image_path

  # Network
  network_name     = var.network_name
  static_ipv4_cidr = var.static_ipv4_cidr
  gateway_ipv4     = var.gateway_ipv4
  dns_servers      = var.dns_servers

  # GPU Passthrough
  enable_gpu_passthrough = var.enable_gpu_passthrough
  gpu_pci_address       = var.gpu_pci_address

  # USB NIC Passthrough
  enable_usb_nic_passthrough = var.enable_usb_nic_passthrough
  usb_nic_vendor_id         = var.usb_nic_vendor_id
  usb_nic_product_id        = var.usb_nic_product_id

  # Authentication
  ssh_authorized_key = var.ssh_authorized_key

  # Tailscale
  enable_tailscale_setup = var.enable_tailscale_setup
  tailscale_tag         = var.tailscale_tag
  ansible_user          = var.ansible_user

  # UEFI
  firmware_path       = var.firmware_path
  nvram_template_path = var.nvram_template_path
  nvram_path          = var.nvram_path
}

output "vm_name" {
  value = module.k3s_gpu_vm.name
}

output "vm_ip" {
  value = module.k3s_gpu_vm.ip_address
}

output "gpu_enabled" {
  value = module.k3s_gpu_vm.gpu_passthrough_enabled
}

output "usb_nic_enabled" {
  value = module.k3s_gpu_vm.usb_nic_passthrough_enabled
}
```

**Create variables.tf**:
```hcl
# Mirror all module variables
variable "name" { type = string }
variable "vcpu" { type = number }
variable "memory_mb" { type = number }
variable "disk_size_gb" { type = number }
variable "data_disk_size_gb" { type = number }
variable "base_image_path" { type = string }
variable "network_name" { type = string }
variable "static_ipv4_cidr" { type = string }
variable "gateway_ipv4" { type = string }
variable "dns_servers" { type = list(string) }
variable "enable_gpu_passthrough" { type = bool }
variable "gpu_pci_address" { type = string }
variable "enable_usb_nic_passthrough" { type = bool }
variable "usb_nic_vendor_id" { type = string }
variable "usb_nic_product_id" { type = string }
variable "ssh_authorized_key" { type = string; sensitive = true }
variable "enable_tailscale_setup" { type = bool }
variable "tailscale_tag" { type = string }
variable "ansible_user" { type = string }
variable "firmware_path" { type = string }
variable "nvram_template_path" { type = string }
variable "nvram_path" { type = string }
```

**Copy terraform.tfvars**:
```bash
cp ../../modules/k3s-vm-gpu/terraform.tfvars .
# Edit as needed
```

---

## Step 4: Deploy VM

### Initialize Terraform

```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/deployments/gaming-laptop
terraform init
```

### Plan Deployment

```bash
terraform plan
```

**Review**:
- VM resources (domain, volumes, cloud-init)
- GPU passthrough null_resource
- USB NIC passthrough null_resource
- Tailscale setup (if enabled)

### Apply Deployment

```bash
terraform apply
```

**Expected Workflow**:
1. Creates base VM with UEFI boot
2. Cloud-init installs packages (including NVIDIA drivers)
3. VM boots and waits for cloud-init completion
4. GPU passthrough: Shuts down VM → attaches GPU → starts VM
5. USB NIC passthrough: Shuts down VM → attaches USB NIC → starts VM
6. Tailscale setup runs (if enabled)

**Duration**: ~10-15 minutes (cloud-init package installation is slowest)

---

## Step 5: Verify Deployment

### Check VM Status

```bash
virsh list --all
# Should show: k3s-gaming-laptop   running
```

### SSH into VM

```bash
ssh ubuntu@192.168.1.102
```

### Verify GPU

```bash
# Inside VM:
lspci | grep -i nvidia
# Should show RTX 3080 Mobile

nvidia-smi
# Should show GPU details, CUDA version, driver version
```

### Verify USB NIC

```bash
# Inside VM:
lsusb
# Should show USB 5GbE adapter

ip link show
# Should show USB NIC interface (e.g., eth1, enx...)
```

### Verify NVIDIA Container Toolkit

```bash
# Inside VM:
which nvidia-container-toolkit
# Should show: /usr/bin/nvidia-container-toolkit

docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
# Should show GPU inside container
```

---

## Step 6: Install K3s

### Install K3s with NVIDIA Device Plugin

```bash
# Inside VM:
curl -sfL https://get.k3s.io | sh -

# Verify K3s is running
sudo k3s kubectl get nodes
# Should show: k3s-gaming-laptop   Ready   control-plane,master
```

### Install NVIDIA Device Plugin for Kubernetes

```bash
sudo k3s kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.0/nvidia-device-plugin.yml
```

### Verify GPU Availability in K3s

```bash
sudo k3s kubectl get nodes "-o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu"
# Should show: k3s-gaming-laptop   1
```

---

## Step 7: Deploy Neo4j + BGE-M3 (Optional)

### Deploy Neo4j with GPU Support

**See**: `/home/morgs/GitRepo/ansible-neo4j-memory/docker/docker-compose.gpu.yml`

This step integrates with the ansible-neo4j-memory project's observability stack.

---

## Troubleshooting

### GPU Not Detected in VM

**Check host VFIO binding**:
```bash
lspci -k -s 01:00.0
# Should show: Kernel driver in use: vfio-pci
```

**Check VM XML**:
```bash
virsh dumpxml k3s-gaming-laptop | grep -A 10 hostdev
# Should show GPU hostdev elements
```

**Re-attach GPU**:
```bash
terraform apply -replace='module.k3s_gpu_vm.null_resource.gpu_passthrough[0]'
```

### USB NIC Not Detected in VM

**Check USB device on host**:
```bash
lsusb | grep 0b95:1790
# Should show USB NIC
```

**Check VM XML**:
```bash
virsh dumpxml k3s-gaming-laptop | grep -A 10 "hostdev.*usb"
# Should show USB hostdev element
```

**Re-attach USB NIC**:
```bash
terraform apply -replace='module.k3s_gpu_vm.null_resource.usb_nic_passthrough[0]'
```

### Cloud-init Not Running

**Check cloud-init status**:
```bash
ssh ubuntu@192.168.1.102
cloud-init status
cat /var/log/cloud-init.log
```

**Common issue**: UEFI cloud-init CDROM not detected
**Solution**: Module includes XSLT fix (cloudinit-cdrom-sata.xsl)

### NVIDIA Driver Installation Failed

**Check cloud-init logs**:
```bash
ssh ubuntu@192.168.1.102
cat /var/log/cloud-init-output.log | grep -i nvidia
```

**Manual installation**:
```bash
ssh ubuntu@192.168.1.102
sudo apt update
sudo apt install -y nvidia-driver-535 nvidia-container-toolkit
sudo reboot
```

---

## Cleanup

### Destroy VM

```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/deployments/gaming-laptop
terraform destroy
```

**Note**: GPU and USB devices will be automatically released back to host.

---

## Next Steps

### 1. Deploy Neo4j GraphRAG Stack

```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/docker
docker-compose -f docker-compose.gpu.yml up -d
```

### 2. Deploy BGE-M3 Embeddings Service

**See**: `/home/morgs/GitRepo/ansible-neo4j-memory/EMBEDDING_STRATEGY.md`

### 3. Run Discovery Playbooks

```bash
cd /home/morgs/GitRepo/ansible-neo4j-memory/ansible/playbooks/discovery
ansible-playbook 00-discover-cluster-standards.yml
```

### 4. Test GPU-Accelerated Embeddings

Deploy Neo4j + BGE-M3 on K3s with GPU acceleration and verify embedding generation performance.

---

## Hardware Specifications

**Gaming Laptop Target**:
- **GPU**: NVIDIA GeForce RTX 3080 Mobile (8GB/16GB VRAM)
- **CPU**: 12 vCPUs allocated to VM
- **RAM**: 29GB allocated to VM
- **Storage**: 500GB root + 1TB data disk
- **Network**: USB 5GbE adapter (passed through)
- **UEFI**: Q35 machine type with OVMF firmware

**K3s Resource Allocation**:
- **Neo4j**: 16GB RAM, GPU for embeddings
- **BGE-M3**: GPU acceleration, 8GB VRAM
- **K3s control plane**: 4GB RAM
- **Other services**: Remaining resources

---

## References

- **Module Documentation**: `/home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu/README.md`
- **Module Summary**: `/home/morgs/GitRepo/ansible-neo4j-memory/infra/terraform/modules/k3s-vm-gpu/MODULE_SUMMARY.md`
- **Base Module**: `/home/morgs/GitRepo/AusterIT_Fresh/infra/terraform/modules/libvirt-k3s-vm/`
- **GPU Passthrough Reference**: `/home/morgs/GitRepo/To Ingest/05-Applications/Edge-Use-Cases/KubeHomeAutomation/scripts/04-create-media-vm-with-gpu.sh`
- **Project Context**: `/home/morgs/GitRepo/ansible-neo4j-memory/CLAUDE.md`
