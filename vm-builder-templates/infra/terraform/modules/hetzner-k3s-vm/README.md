# Hetzner Cloud K3s VM Module

Terraform module for provisioning K3s-ready VMs on Hetzner Cloud.

## Features

- **Ultra-cheap testing**: €0.55/day for development (cx22 instance)
- **Hourly billing**: Only pay for hours used
- **Cloud-init bootstrap**: Automatic GitHub Actions runner setup
- **Tailscale-ready**: Network configuration for Tailscale mesh
- **BWS integration**: Inventory management built-in
- **Same patterns as libvirt**: Drop-in replacement for local development

## Cost

| Server Type | vCPU | RAM | Price/mo | Price/hour |
|-------------|------|-----|----------|------------|
| **cx22** | 2 | 4GB | €4.15 | €0.0055 |
| cx32 | 4 | 8GB | €12.90 | €0.017 |
| cpx31 | 4 | 8GB | €17.35 | €0.023 |

**Development strategy**: Spin up for 4 hours/day = €0.022/day = **€0.66 for 30 days of testing**

## Prerequisites

1. Hetzner Cloud account (https://console.hetzner.cloud/)
2. Hetzner Cloud API token:
   - Go to: Project → Security → API Tokens
   - Create new token with **Read & Write** permissions
   - Export: `export HCLOUD_TOKEN=<your-token>`

## Quick Start

### 1. Basic VM

```hcl
module "test_vm" {
  source = "../../modules/hetzner-k3s-vm"

  name                = "test-k3s-vm"
  server_type         = "cx22"  # 2 vCPU, 4GB, €4.15/mo
  location            = "nbg1"  # Nuremberg (cheapest)

  ssh_authorized_keys = [
    "ssh-ed25519 AAAAC3... your-key"
  ]

  # GitHub runner (optional)
  runner_token          = var.runner_token
  ssh_private_key_b64   = var.ssh_private_key_b64
  github_repo           = "mightymorgs/k8s-platform-automation"
  github_runner_version = "2.332.0"
}

output "vm_ip" {
  value = module.test_vm.ipv4_address
}
```

### 2. Apply

```bash
cd infra/terraform/examples/hetzner-test
terraform init
terraform plan
terraform apply

# VM will be ready in ~60 seconds
# SSH: ssh ubuntu@<ip-address>
```

### 3. Destroy When Done

```bash
terraform destroy  # Stop billing immediately
```

## Integration with Existing Workflows

This module is designed to replace the libvirt module for cloud testing:

**Phase 2 Workflow Changes**:

```yaml
# .github/workflows/phase2-provision-vm-hetzner.yml
- name: Set Terraform module based on hypervisor type
  run: |
    if [ "$HYPERVISOR_TYPE" = "hetzner" ]; then
      export TG_MODULE_SOURCE="/tmp/tg/infra/terraform/modules/hetzner-k3s-vm"
    else
      export TG_MODULE_SOURCE="/tmp/tg/infra/terraform/modules/k3s-vm-gpu"
    fi
```

## Variables

### Required

- `name` - VM hostname (RFC 1123 compliant)
- `ssh_authorized_keys` - List of SSH public keys

### Common Options

- `server_type` - Instance size (default: `cx22`)
- `location` - Datacenter (default: `nbg1`)
- `runner_token` - GitHub Actions ephemeral token
- `ssh_private_key_b64` - Base64-encoded deploy key
- `bws_access_token` - BWS token for inventory
- `inventory_key` - BWS inventory path

### Advanced

- `enable_floating_ip` - Static IP across rebuilds (€1.19/mo)
- `data_volume_size_gb` - Additional storage (€0.0476/GB/mo)
- `private_network_id` - Hetzner private network
- `firewall_ids` - Hetzner firewall rules (optional, Tailscale recommended)

## Outputs

- `ipv4_address` - Public IP (use this for SSH/Tailscale)
- `server_id` - Hetzner server ID
- `floating_ip` - Static IP (if enabled)
- `status` - Server status

## Cost Control

### Auto-Destroy Pattern

Add to your repo:

```yaml
# .github/workflows/destroy-test-vm.yml
name: Nightly Cleanup
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM UTC
  workflow_dispatch:

jobs:
  destroy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Destroy test VM
        env:
          HCLOUD_TOKEN: ${{ secrets.HCLOUD_TOKEN }}
        run: |
          cd infra/terraform/live/hetzner-test
          terraform init
          terraform destroy -auto-approve
```

**Result**: VM only runs during your work hours, €0 overnight.

## Comparison: Hetzner vs Libvirt

| Feature | Libvirt | Hetzner |
|---------|---------|---------|
| **Access** | Needs iMac | Any browser |
| **Speed** | 5-10 min | 60 seconds |
| **Cost** | Free (your hardware) | €0.0055/hour |
| **Network** | Bridge setup required | Public IP automatic |
| **GPU passthrough** | Yes | No |
| **Multi-tenant** | Hypervisor required | Native cloud |

## Migration Path

**Week 1**: Build on Hetzner (€2.75 total for MVP)
**Week 2**: Move to Oracle Free Tier (€0 forever)
**Production**: Keep libvirt module for on-prem

## Examples

See `infra/terraform/examples/hetzner-test/` for full working example.

## Troubleshooting

### "Error 401: Unauthorized"
- Check `HCLOUD_TOKEN` is exported
- Verify token has Read & Write permissions

### "Server creation failed: resource limit exceeded"
- Hetzner has limits on new accounts
- Contact support or wait 24 hours

### VM not becoming ready
- Check Hetzner Cloud console
- SSH to public IP and check `/var/log/cloud-init-output.log`

## Next Steps

1. Test basic VM creation
2. Verify GitHub runner connects
3. Run Phase 2.5 bootstrap playbook
4. Deploy media stack for testing

## License

Apache 2.0
