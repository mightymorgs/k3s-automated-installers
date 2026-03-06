terraform {
  required_version = ">= 1.5.0"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.8.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.0"
    }
  }
}

provider "libvirt" {
  uri = var.libvirt_uri
}

locals {
  root_disk_size_bytes = var.disk_size_gb * 1073741824
  data_disk_size_bytes = var.data_disk_size_gb * 1073741824

  # USB NIC static IP netplan configuration (for passthrough mode)
  # USB NIC is always on public network (192.168.0.x), not NAT network
  usb_nic_netplan_config = <<YAML
network:
  version: 2
  renderer: networkd
  ethernets:
    usb-nic:
      match:
        name: enx*
      dhcp4: false
      addresses: [${var.usb_nic_static_ip}/24]
      routes:
        - to: default
          via: ${var.usb_nic_gateway}
          metric: 50
      nameservers:
        addresses: [${join(", ", var.dns_servers)}]
YAML

  # Choose USB NIC netplan or empty string based on passthrough setting
  usb_nic_netplan = var.enable_usb_nic_passthrough && var.usb_nic_static_ip != "" ? local.usb_nic_netplan_config : ""

  # Prefer matching by MAC for reliability; fallback to interface name pattern
  # Netplan templates have NO indentation - used in cloud-init content: | which preserves exact spacing
  network_cfg_static_by_mac  = <<YAML
network:
  version: 2
  renderer: networkd
  ethernets:
    nic0:
      match:
        macaddress: ${var.mac != null ? lower(var.mac) : ""}
      set-name: eth0
      dhcp4: false
      addresses: [${var.static_ipv4_cidr}]
      routes:
        - to: default
          via: ${var.gateway_ipv4}
      nameservers:
        addresses: [${join(", ", var.dns_servers)}]
YAML
  network_cfg_static_by_name = <<YAML
network:
  version: 2
  renderer: networkd
  ethernets:
    default:
      match:
        name: "en*"
      dhcp4: false
      dhcp6: false
      addresses: [${var.static_ipv4_cidr}]
      routes:
        - to: default
          via: ${var.gateway_ipv4}
      nameservers:
        addresses: [${join(", ", var.dns_servers)}]
YAML
  network_cfg_dhcp_by_mac    = <<YAML
network:
  version: 2
  renderer: networkd
  ethernets:
    default:
      match:
        macaddress: ${var.mac != null ? lower(var.mac) : ""}
      dhcp4: true
      dhcp6: false
YAML
  network_cfg_dhcp_by_name   = <<YAML
network:
  version: 2
  renderer: networkd
  ethernets:
    default:
      match:
        name: "en*"
      dhcp4: true
      dhcp6: false
YAML
  network_cfg_static         = (var.mac != null && var.mac != "") ? local.network_cfg_static_by_mac : local.network_cfg_static_by_name
  network_cfg_dhcp           = (var.mac != null && var.mac != "") ? local.network_cfg_dhcp_by_mac : local.network_cfg_dhcp_by_name
  # Netplan file content (will be written by cloud-init write_files with content: | block scalar)
  netplan_file = var.static_ipv4_cidr != "" ? local.network_cfg_static : local.network_cfg_dhcp

  # Parse GPU PCI address (format: 01:00.0)
  gpu_pci_parts = var.enable_gpu_passthrough ? split(":", replace(var.gpu_pci_address, ".", ":")) : []
  gpu_bus       = var.enable_gpu_passthrough ? "0x${local.gpu_pci_parts[0]}" : ""
  gpu_slot      = var.enable_gpu_passthrough ? "0x${local.gpu_pci_parts[1]}" : ""
  gpu_func      = var.enable_gpu_passthrough ? "0x${local.gpu_pci_parts[2]}" : ""

  user_data = <<YAML
#cloud-config
hostname: ${var.name}
manage_etc_hosts: true
bootcmd:
  - mkdir -p /root/.ssh
  - chmod 700 /root/.ssh
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: ["adm", "sudo"]
    shell: /bin/bash
    ssh_authorized_keys:
%{ for key in var.ssh_authorized_keys ~}
      - ${key}
%{ endfor ~}
%{if var.admin_user != ""~}
  - name: ${var.admin_user}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: ["adm", "sudo"]
    shell: /bin/bash
    lock_passwd: false
    ssh_authorized_keys:
%{ for key in var.ssh_authorized_keys ~}
      - ${key}
%{ endfor ~}
%{endif~}
ssh_pwauth: ${var.enable_console_pw || var.admin_user != "" ? "true" : "false"}
%{if var.enable_console_pw || var.admin_user != ""~}
chpasswd:
  list: |
%{if var.enable_console_pw~}
    ubuntu:${var.console_password}
%{endif~}
%{if var.admin_user != ""~}
    ${var.admin_user}:${var.admin_password}
%{endif~}
  expire: False
%{endif~}
write_files:
%{if var.enable_usb_nic_passthrough && var.usb_nic_static_ip != ""~}
  - path: /etc/netplan/60-usb-nic.yaml
    permissions: '0600'
    content: |
      ${indent(6, local.usb_nic_netplan)}
%{endif~}
%{if var.console_authorized_key != ""~}
  - path: /root/.ssh/authorized_keys
    permissions: '0600'
    owner: root
    group: root
    content: |
      ${var.console_authorized_key}
    append: true
%{endif~}
package_update: true
packages:
  - qemu-guest-agent
  - curl
  - gnupg
  - jq
runcmd:
  - systemctl enable --now qemu-guest-agent
%{if var.enable_tailscale_setup && var.tailscale_auth_key != ""~}
  - |
    # Join Tailscale with pre-generated auth key
    echo "Joining Tailscale network..."
    tailscale up --authkey='${var.tailscale_auth_key}' --ssh --hostname=${var.name}
    echo "Tailscale joined successfully"
%{endif~}
%{if var.enable_usb_nic_passthrough~}
  - |
    set -e
    echo "Installing USB NIC drivers..."
    # Fix any dpkg issues first
    dpkg --configure -a || true
    apt-get clean
    apt-get -f install -y || true
    # Install linux-modules-extra with retry
    MAX_RETRIES=3
    RETRY=0
    while [ $RETRY -lt $MAX_RETRIES ]; do
      if apt-get install -y linux-modules-extra-$(uname -r); then
        echo "linux-modules-extra installed"
        modprobe r8152 || true
        echo "r8152" >> /etc/modules-load.d/usb-nic.conf
        exit 0
      fi
      RETRY=$((RETRY + 1))
      sleep 10
    done
%{endif~}
# NOTE: NVIDIA driver installation moved to separate Ansible playbook
# Cloud-init installing drivers during first boot takes 30+ minutes and blocks SSH
# Install drivers AFTER VM is accessible via: ansible-playbook install-nvidia-drivers.yml
  - |
    set -e
    echo "Waiting for DNS resolution..."
    MAX_DNS_WAIT=30
    DNS_WAIT=0
    while [ $DNS_WAIT -lt $MAX_DNS_WAIT ]; do
      if nslookup tailscale.com >/dev/null 2>&1 || host tailscale.com >/dev/null 2>&1; then
        echo "DNS resolution working"
        break
      fi
      DNS_WAIT=$((DNS_WAIT + 1))
      sleep 2
    done
    if [ $DNS_WAIT -eq $MAX_DNS_WAIT ]; then
      echo "WARNING: DNS resolution timeout after 60 seconds, attempting Tailscale install anyway"
    fi
    echo "Installing Tailscale..."
    MAX_RETRIES=3
    RETRY=0
    while [ $RETRY -lt $MAX_RETRIES ]; do
      if curl -fsSL https://tailscale.com/install.sh | sh; then
        echo "Tailscale installed successfully"
        exit 0
      fi
      RETRY=$((RETRY + 1))
      if [ $RETRY -lt $MAX_RETRIES ]; then
        echo "Attempt $RETRY failed, retrying in 5 seconds..."
        sleep 5
      fi
    done
    echo "ERROR: Tailscale installation failed after $MAX_RETRIES attempts" | tee /var/log/tailscale-install-error.log
    exit 1
%{if var.enable_github_runner && var.runner_token != ""~}
  - |
    # Install GitHub Actions self-hosted runner
    set -e
    echo "Setting up GitHub Actions runner..."
    RUNNER_VERSION="${var.github_runner_version}"
    RUNNER_ORG="${var.github_repo}"
    RUNNER_TOKEN='${var.runner_token}'
    RUNNER_LABELS='${var.github_runner_labels},${var.name}'

    # Create runner user
    useradd -m -d /home/runner -s /bin/bash runner || true

    # Download and install runner
    cd /home/runner
    mkdir -p actions-runner && cd actions-runner
    curl -o actions-runner-linux-x64-$RUNNER_VERSION.tar.gz -L \
      https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz
    tar xzf ./actions-runner-linux-x64-$RUNNER_VERSION.tar.gz
    chown -R runner:runner /home/runner/actions-runner

    # Register runner (as runner user)
    su - runner -c "/home/runner/actions-runner/config.sh \
      --url https://github.com/$RUNNER_ORG \
      --token $RUNNER_TOKEN \
      --labels $RUNNER_LABELS \
      --unattended"

    # Install and start service
    cd /home/runner/actions-runner
    ./svc.sh install runner
    ./svc.sh start
    echo "GitHub Actions runner installed and started" | tee /var/log/github-runner-setup.log
%{endif~}
YAML

  # New minimal bootstrap cloud-init (used when runner_token is provided)
  user_data_bootstrap = var.runner_token != "" ? templatefile("${path.module}/templates/cloud-init-bootstrap.yaml.j2", {
    vm_name               = var.name
    ssh_private_key_b64   = var.ssh_private_key_b64
    runner_token          = var.runner_token
    github_repo           = var.github_repo
    github_runner_version = var.github_runner_version
    # Network configuration (use existing netplan_file local with NO indentation)
    netplan_content       = local.netplan_file
    # SSH access
    ssh_authorized_keys   = var.ssh_authorized_keys
    # Console access (sourced from BWS: inventory/shared/secrets/console/*)
    console_username      = var.console_username
    console_password      = var.console_password
  }) : ""

  meta_data = <<YAML
instance-id: ${var.name}
local-hostname: ${var.name}
YAML
}

resource "libvirt_volume" "base" {
  name   = "${var.name}-base"
  pool   = "default"
  source = var.base_image_path
  format = "qcow2"
}

resource "libvirt_volume" "root" {
  name           = "${var.name}-root"
  pool           = "default"
  base_volume_id = libvirt_volume.base.id
  size           = local.root_disk_size_bytes
  format         = "qcow2"
}

resource "libvirt_volume" "data" {
  count  = var.data_disk_size_gb > 0 ? 1 : 0
  name   = "${var.name}-data"
  pool   = "default"
  size   = local.data_disk_size_bytes
  format = "qcow2"
}

resource "libvirt_cloudinit_disk" "cloudinit" {
  name = "${var.name}-cloudinit.iso"
  # Priority: 1) J2-rendered content (base64 decoded), 2) bootstrap template, 3) legacy user_data
  user_data = (
    var.user_data_content_b64 != "" ? base64decode(var.user_data_content_b64) :
    local.user_data_bootstrap != "" ? local.user_data_bootstrap :
    local.user_data
  )
  meta_data      = local.meta_data
  network_config = local.netplan_file
}

resource "libvirt_domain" "vm" {
  name   = var.name
  vcpu   = var.vcpu
  memory = var.memory_mb

  lifecycle {
    precondition {
      condition     = var.admin_user == "" || var.admin_password != ""
      error_message = "admin_password must be provided when admin_user is set."
    }
    precondition {
      condition     = !var.enable_gpu_passthrough || var.gpu_pci_address != ""
      error_message = "gpu_pci_address must be provided when enable_gpu_passthrough is true."
    }
    precondition {
      condition     = !var.enable_usb_nic_passthrough || (var.usb_nic_vendor_id != "" && var.usb_nic_product_id != "")
      error_message = "usb_nic_vendor_id and usb_nic_product_id must be provided when enable_usb_nic_passthrough is true."
    }
    precondition {
      condition     = var.static_ipv4_cidr == "" || var.gateway_ipv4 != ""
      error_message = "gateway_ipv4 must be provided when using static IP configuration (static_ipv4_cidr is set)."
    }
  }

  cpu {
    mode = "host-passthrough"
  }

  qemu_agent = true
  autostart  = true

  # XSLT transformation to change cloud-init disk from IDE to SATA for UEFI/OVMF compatibility
  # Q35/UEFI machines don't properly detect IDE bus, causing cloud-init to not run
  xml {
    xslt = file("${path.module}/cloudinit-cdrom-sata.xsl")
  }

  # UEFI boot (OVMF) for Ubuntu 24.04 cloud image
  # Configurable paths support different Linux distributions (Debian/Ubuntu, Fedora/RHEL, Arch)
  # Set firmware_path to "" to use legacy BIOS boot instead
  firmware = var.firmware_path != "" ? var.firmware_path : null

  dynamic "nvram" {
    for_each = var.firmware_path != "" ? [1] : []
    content {
      file     = "${var.nvram_path}/${var.name}_VARS.fd"
      template = var.nvram_template_path
    }
  }

  boot_device {
    dev = ["hd"]
  }

  cloudinit = libvirt_cloudinit_disk.cloudinit.id

  disk {
    volume_id = libvirt_volume.root.id
  }

  dynamic "disk" {
    for_each = var.data_disk_size_gb > 0 ? [1] : []
    content {
      volume_id = libvirt_volume.data[0].id
    }
  }

  network_interface {
    network_name = var.network_name
    mac          = var.mac
  }

  # GPU and USB NIC passthrough handled via XSLT transformation above
  # Cannot use dynamic hostdev blocks as libvirt provider doesn't support them
  # Instead, XML is modified via add-passthrough.xsl template

  graphics {
    type           = "spice"
    listen_type    = "address"
    listen_address = "127.0.0.1"
    autoport       = true
  }

  console {
    type        = "pty"
    target_type = "virtio"
    target_port = "0"
  }

  # domain implicitly depends on volumes and cloudinit
}

# Tailscale setup via Ansible (optional)
resource "null_resource" "tailscale_setup" {
  # DISABLED: VM joins Tailscale in Phase 2.5 via bootstrap orchestration playbook
  # Self-bootstrap design: VM runs GitHub Actions runner which executes 01-join-via-oauth.yml
  count = 0  # Disabled - was: var.enable_tailscale_setup && var.tailscale_tag != "" && var.static_ipv4_cidr != "" ? 1 : 0

  # Trigger on VM recreation or tag change
  triggers = {
    vm_id         = libvirt_domain.vm.id
    tailscale_tag = var.tailscale_tag
    vm_ip         = split("/", var.static_ipv4_cidr)[0]
  }

  # Wait for VM to be accessible via SSH
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Waiting for VM ${var.name} to be accessible..."
      MAX_ATTEMPTS=60
      ATTEMPT=0
      VM_IP="${split("/", var.static_ipv4_cidr)[0]}"

      while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
        if ssh -o StrictHostKeyChecking=no \
               -o UserKnownHostsFile=/dev/null \
               -o ConnectTimeout=5 \
               ${var.ansible_user}@$VM_IP \
               "echo 'SSH ready'" 2>/dev/null; then
          echo "VM ${var.name} is accessible at $VM_IP"

          # Wait for cloud-init to complete (with 10 minute timeout)
          echo "Waiting for cloud-init to complete..."
          if ! timeout 600 ssh -o StrictHostKeyChecking=no \
                  -o UserKnownHostsFile=/dev/null \
                  -o ConnectTimeout=10 \
                  ${var.ansible_user}@$VM_IP \
                  "cloud-init status --wait"; then
            echo "ERROR: cloud-init did not complete within 10 minutes or had errors"
            exit 1
          fi

          # Verify Tailscale was installed successfully
          echo "Verifying Tailscale installation..."
          if ! ssh -o StrictHostKeyChecking=no \
                  -o UserKnownHostsFile=/dev/null \
                  ${var.ansible_user}@$VM_IP \
                  "which tailscale && tailscale version"; then
            echo "ERROR: Tailscale not installed correctly"
            exit 1
          fi

          echo "VM ${var.name} is fully ready at $VM_IP with Tailscale installed"
          break
        fi
        ATTEMPT=$((ATTEMPT + 1))
        echo "Attempt $ATTEMPT/$MAX_ATTEMPTS: VM not ready yet, waiting..."
        sleep 5
      done

      if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        echo "ERROR: VM ${var.name} did not become accessible at $VM_IP within timeout (5 minutes)"
        exit 1
      fi
    EOT
  }

  # Join Tailscale via QEMU guest agent (no SSH required)
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Joining ${var.name} to Tailscale via QEMU guest agent..."

      # Use virsh qemu-agent-command to run tailscale up
      # Auth key was already passed via cloud-init and should have run
      # This is just verification
      MAX_WAIT=30
      WAIT=0
      while [ $WAIT -lt $MAX_WAIT ]; do
        # Check if VM is on Tailscale by checking status
        if virsh qemu-agent-command ${var.name} '{"execute":"guest-exec","arguments":{"path":"/usr/bin/tailscale","arg":["status"],"capture-output":true}}' 2>/dev/null | grep -q "pid"; then
          echo "Tailscale command executed"
          sleep 2
          break
        fi
        WAIT=$((WAIT + 1))
        sleep 2
      done
      echo "Tailscale setup completed for ${var.name}"
    EOT
  }

  depends_on = [libvirt_domain.vm]
}

# ⚠️ GPU passthrough is handled by Ansible playbooks (NOT Terraform)
# Terraform local-exec provisioner runs on client, not libvirt host
# See: ansible/playbooks/infrastructure/05-attach-gpu-passthrough.yml
resource "null_resource" "gpu_passthrough" {
  count = 0  # DISABLED - Ansible handles GPU attachment

  triggers = {
    vm_id           = libvirt_domain.vm.id
    gpu_pci_address = var.gpu_pci_address
  }

  # Create GPU hostdev XML files
  provisioner "local-exec" {
    command = <<-EOT
      set -e

      # Create temporary XML files for GPU passthrough
      GPU_XML_FUNC0=$(mktemp /tmp/gpu-func0-XXXXXX.xml)
      GPU_XML_FUNC1=$(mktemp /tmp/gpu-func1-XXXXXX.xml)

      # GPU Function 0 (primary)
      cat > $GPU_XML_FUNC0 <<EOF
<hostdev mode='subsystem' type='pci' managed='yes'>
  <source>
    <address domain='0x0000' bus='${local.gpu_bus}' slot='${local.gpu_slot}' function='${local.gpu_func}'/>
  </source>
  <address type='pci' multifunction='on'/>
</hostdev>
EOF

      # GPU Function 1 (audio)
      cat > $GPU_XML_FUNC1 <<EOF
<hostdev mode='subsystem' type='pci' managed='yes'>
  <source>
    <address domain='0x0000' bus='${local.gpu_bus}' slot='${local.gpu_slot}' function='0x1'/>
  </source>
  <address type='pci'/>
</hostdev>
EOF

      echo "Shutting down VM ${var.name} to attach GPU..."
      virsh shutdown ${var.name} || true
      sleep 5

      echo "Attaching GPU function 0 (${var.gpu_pci_address})..."
      virsh attach-device ${var.name} $GPU_XML_FUNC0 --config

      echo "Attaching GPU function 1 (audio)..."
      virsh attach-device ${var.name} $GPU_XML_FUNC1 --config

      echo "Starting VM ${var.name}..."
      virsh start ${var.name}

      rm -f $GPU_XML_FUNC0 $GPU_XML_FUNC1
      echo "GPU passthrough configured successfully"
    EOT
  }

  depends_on = [libvirt_domain.vm]
}

# ⚠️ USB NIC passthrough is handled by Ansible playbooks (NOT Terraform)
# See: ansible/playbooks/infrastructure/06-attach-usb-nic-passthrough.yml
resource "null_resource" "usb_nic_passthrough" {
  count = 0  # DISABLED - Ansible handles USB NIC attachment

  triggers = {
    vm_id             = libvirt_domain.vm.id
    usb_nic_vendor_id = var.usb_nic_vendor_id
    usb_nic_product_id = var.usb_nic_product_id
  }

  # Create USB hostdev XML file
  provisioner "local-exec" {
    command = <<-EOT
      set -e

      # Create temporary XML file for USB NIC passthrough
      USB_XML=$(mktemp /tmp/usb-nic-XXXXXX.xml)

      cat > $USB_XML <<EOF
<hostdev mode='subsystem' type='usb' managed='yes'>
  <source>
    <vendor id='0x${var.usb_nic_vendor_id}'/>
    <product id='0x${var.usb_nic_product_id}'/>
  </source>
</hostdev>
EOF

      echo "Shutting down VM ${var.name} to attach USB NIC..."
      virsh shutdown ${var.name} || true
      sleep 5

      echo "Attaching USB 5GbE NIC (${var.usb_nic_vendor_id}:${var.usb_nic_product_id})..."
      virsh attach-device ${var.name} $USB_XML --config

      echo "Starting VM ${var.name}..."
      virsh start ${var.name}

      rm -f $USB_XML
      echo "USB NIC passthrough configured successfully"
    EOT
  }

  depends_on = [libvirt_domain.vm, null_resource.gpu_passthrough]
}
