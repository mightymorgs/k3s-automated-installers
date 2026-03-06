# NOTE: This file is overwritten during CI by rendering terragrunt.hcl.j2.
# This static version is kept for local development and documentation.
# Include root configuration for DRY pattern
include "root" {
  path = find_in_parent_folders()
}

# VM-specific inputs only (root handles backend/module)
# Inputs are supplied via environment to keep secrets out of git.
# The GitHub Actions workflow composes TG_* env vars from Bitwarden inventory.
#
# VM Naming Convention (7 components):
# Format: {client}-{vmtype}-{subtype}-{state}-{purpose}-{platform}-{version}
#
# Components:
#   {client}   - homelab | austerit | clientname (TF Cloud workspace)
#   {vmtype}   - k3s | docker | vm
#   {subtype}  - master | worker | standalone
#   {state}    - prod | staging | dev | test
#   {purpose}  - mediastack | coreinfra | webapp (compound word, no underscores)
#   {platform} - libvirt | gcp | aws | hetzner | azure
#   {version}  - latest | v1.0.0 | stable
#
# Examples:
#   homelab-k3s-master-prod-mediastack-libvirt-latest
#   homelab-k3s-master-staging-mediastack-gcp-latest
#   austerit-k3s-master-prod-coreinfra-hetzner-v1.2.0
#   clientname-k3s-worker-staging-webapp-aws-latest
#
inputs = {
  name                   = get_env("TG_NAME", "homelab-k3s-master-test-mediastack-libvirt-latest")
  vcpu                   = tonumber(get_env("TG_VCPU", "12"))
  memory_mb              = tonumber(get_env("TG_MEMORY_MB", "24576"))
  disk_size_gb           = tonumber(get_env("TG_DISK_SIZE_GB", "120"))
  data_disk_size_gb      = tonumber(get_env("TG_DATA_DISK_SIZE_GB", "200"))
  base_image_path        = get_env("TG_BASE_IMAGE_PATH", "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img")
  network_name           = get_env("TG_NETWORK_NAME", "default")
  mac                    = get_env("TG_MAC", "") != "" ? get_env("TG_MAC", "") : null
  static_ipv4_cidr       = get_env("TG_STATIC_IPV4_CIDR", "")
  gateway_ipv4           = get_env("TG_GATEWAY_IPV4", "")
  dns_servers            = split(",", get_env("TG_DNS_SERVERS_CSV", "1.1.1.1,8.8.8.8"))
  ssh_authorized_keys    = split(",", get_env("TG_SSH_AUTH_KEYS_CSV", ""))
  ansible_user           = get_env("TG_ANSIBLE_USER", "ubuntu")
  enable_gpu_passthrough = tobool(get_env("TG_ENABLE_GPU_PASSTHROUGH", "false"))
  gpu_pci_address        = get_env("TG_GPU_PCI_ADDRESS", "")
  enable_tailscale_setup = tobool(get_env("TG_ENABLE_TAILSCALE", "true"))
  tailscale_tag          = "tag:${get_env("TG_NAME", "homelab-k3s-master-test-mediastack-libvirt-latest")}"
  tailscale_auth_key     = get_env("TG_TAILSCALE_AUTH_KEY", "")
  enable_github_runner   = tobool(get_env("TG_ENABLE_GITHUB_RUNNER", "true"))
  github_runner_token    = get_env("TG_GITHUB_RUNNER_TOKEN", "")
  github_runner_labels   = get_env("TG_GITHUB_RUNNER_LABELS", "self-hosted,libvirt")
  github_runner_version  = get_env("TG_GITHUB_RUNNER_VERSION", "2.331.0")

  # Cloud-init bootstrap variables (Phase 2 workflow sets these)
  bws_access_token    = get_env("TG_BWS_ACCESS_TOKEN", "")
  inventory_key       = get_env("TG_INVENTORY_KEY", "")
  runner_token        = get_env("TG_RUNNER_TOKEN", "")
  ssh_private_key_b64 = get_env("TG_SSH_PRIVATE_KEY_B64", "")
  github_repo         = get_env("TG_GITHUB_REPO", "")

  # Console access credentials (sourced from BWS: inventory/shared/secrets/console/*)
  # For QEMU VM viewer fallback access when SSH/Tailscale isn't working
  console_username    = get_env("TG_CONSOLE_USERNAME", "")
  console_password    = get_env("TG_CONSOLE_PASSWORD", "")

  # Pre-rendered cloud-init from J2 template (BASE64 ENCODED to avoid shell variable interpolation)
  # Decoded by Terraform using base64decode()
  user_data_content_b64 = get_env("TG_USER_DATA_CONTENT_B64", "")
}
