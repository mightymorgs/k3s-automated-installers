# Terragrunt Configuration

This directory contains Terragrunt configurations for managing infrastructure across multiple environments and clients using the DRY (Don't Repeat Yourself) pattern.

## Directory Structure

### Current Structure

```
infra/terragrunt/
├── terragrunt.hcl                              # Root config (DRY - common configuration)
└── live/
    └── media-stack-single-node/                # Current single-node deployment
        └── terragrunt.hcl                      # VM-specific inputs only
```

### Recommended Future Structure

As your infrastructure grows to support multiple clients and environments, the recommended directory structure is:

```
infra/terragrunt/
├── terragrunt.hcl                              # Root config (DRY)
└── live/
    ├── homelab/                                # Client: homelab
    │   ├── staging/
    │   │   └── media_stack/
    │   │       └── terragrunt.hcl              # Homelab staging media stack
    │   └── prod/
    │       └── media_stack/
    │           └── terragrunt.hcl              # Homelab production media stack
    └── austerit/                               # Client: AusterIT
        ├── staging/
        │   └── core_infra/
        │       └── terragrunt.hcl              # AusterIT staging infrastructure
        └── prod/
            └── core_infra/
                └── terragrunt.hcl              # AusterIT production infrastructure
```

## Root Configuration Pattern

The root `terragrunt.hcl` file implements the DRY pattern by extracting common configuration that is shared across all environments:

### What's Centralized (Root Config)

- **Remote State Configuration**: Terraform Cloud backend setup
- **Module Source**: GitHub-hosted Terraform module reference
- **Workspace Logic**: Client-based workspace naming derived from directory structure
- **Common Variables**: Shared defaults (can be overridden by child configs)

### What's Environment-Specific (Child Configs)

- **VM Specifications**: CPU, memory, disk sizes
- **Network Configuration**: IP addresses, MAC addresses, DNS servers
- **Feature Flags**: GPU passthrough, Tailscale, GitHub runner settings
- **Secrets**: All secrets are provided via environment variables (never committed to Git)

## How It Works

### 1. Root Configuration

The root `terragrunt.hcl` file uses `path_relative_to_include()` to parse the directory structure and automatically determine:

- **Client name**: First directory component (e.g., `homelab`, `austerit`)
- **Environment**: Second directory component (e.g., `staging`, `prod`)
- **Workload**: Third directory component (e.g., `media_stack`, `core_infra`)

**Example:**

For a config at `live/homelab/staging/media_stack/terragrunt.hcl`:
- Client: `homelab`
- Environment: `staging`
- Workload: `media_stack`
- Terraform Cloud Workspace: `homelab`

### 2. Child Configuration

Each child `terragrunt.hcl` includes the root configuration and specifies only VM-specific inputs:

```hcl
include "root" {
  path = find_in_parent_folders()
}

inputs = {
  name = get_env("TG_NAME", "homelab-k3s-master-staging-media_stack-latest")
  vcpu = tonumber(get_env("TG_VCPU", "12"))
  # ... other VM-specific inputs
}
```

### 3. Environment Variables

All secrets and configuration values are provided via environment variables:

- **Terraform Cloud**: `TF_CLOUD_TOKEN`, `TG_TFC_ORGANIZATION`
- **VM Configuration**: `TG_NAME`, `TG_VCPU`, `TG_MEMORY_MB`, etc.
- **Network Settings**: `TG_STATIC_IPV4_CIDR`, `TG_GATEWAY_IPV4`, `TG_DNS_SERVERS_CSV`
- **Feature Flags**: `TG_ENABLE_GPU_PASSTHROUGH`, `TG_ENABLE_TAILSCALE`, `TG_ENABLE_GITHUB_RUNNER`
- **Secrets**: `TG_TAILSCALE_AUTH_KEY`, `TG_GITHUB_RUNNER_TOKEN`, `TG_SSH_AUTH_KEYS_CSV`

These are composed by GitHub Actions workflows from Bitwarden Secrets Manager (BWS) inventory.

## Terraform Cloud Integration

### Workspace Organization

Workspaces are organized by **client name** (first directory component):

- **Workspace: `homelab`** → All homelab VMs share this workspace
  - `homelab-k3s-master-staging-media_stack-latest`
  - `homelab-k3s-master-prod-media_stack-v1.0.0`
  - Future: `homelab-docker-standalone-dev-portainer-latest`

- **Workspace: `austerit`** → All AusterIT VMs share this workspace
  - `austerit-k3s-master-prod-core_infra-v1.2.0`
  - `austerit-k3s-worker-prod-core_infra-v1.2.0`

### Why Client-Based Workspaces?

- **Simplified State Management**: All VMs for a client in one workspace
- **Easier Collaboration**: Team members can view all client infrastructure
- **Resource Dependencies**: VMs within a client can reference each other's state
- **Cost Tracking**: Terraform Cloud usage aligns with client boundaries

### Accessing State

- **Web UI**: https://app.terraform.io/app/mightymorgs/workspaces/homelab
- **API**: Via `TF_CLOUD_TOKEN` (stored in BWS + GitHub Secrets)

## Module Source

The Terraform module is referenced from GitHub:

```hcl
source = "github.com/mightymorgs/media-stack//infra/terraform/modules/k3s-vm-gpu?ref=main"
```

### Development Override

For local development, you can override the module source:

```bash
export TG_MODULE_SOURCE="${PWD}/infra/terraform/modules/k3s-vm-gpu"
```

This allows you to test module changes without pushing to GitHub.

## Usage Examples

### Current Setup (Flat Structure)

```bash
cd infra/terragrunt/live/media-stack-single-node
terragrunt plan
terragrunt apply
```

### Future Setup (Multi-Client Structure)

**Deploy homelab staging environment:**

```bash
cd infra/terragrunt/live/homelab/staging/media_stack
terragrunt plan
terragrunt apply
```

**Deploy AusterIT production environment:**

```bash
cd infra/terragrunt/live/austerit/prod/core_infra
terragrunt plan
terragrunt apply
```

## Adding a New Environment

### Step 1: Create Directory Structure

```bash
# For a new client deployment
mkdir -p infra/terragrunt/live/clientname/staging/webapp
```

### Step 2: Create Child Config

```bash
cat > infra/terragrunt/live/clientname/staging/webapp/terragrunt.hcl <<'EOF'
include "root" {
  path = find_in_parent_folders()
}

inputs = {
  name                   = get_env("TG_NAME", "clientname-k3s-master-staging-webapp-latest")
  vcpu                   = tonumber(get_env("TG_VCPU", "8"))
  memory_mb              = tonumber(get_env("TG_MEMORY_MB", "16384"))
  disk_size_gb           = tonumber(get_env("TG_DISK_SIZE_GB", "100"))
  data_disk_size_gb      = tonumber(get_env("TG_DATA_DISK_SIZE_GB", "150"))
  base_image_path        = get_env("TG_BASE_IMAGE_PATH", "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img")
  network_name           = get_env("TG_NETWORK_NAME", "br0")
  mac                    = get_env("TG_MAC", "")
  static_ipv4_cidr       = get_env("TG_STATIC_IPV4_CIDR", "")
  gateway_ipv4           = get_env("TG_GATEWAY_IPV4", "")
  dns_servers            = split(",", get_env("TG_DNS_SERVERS_CSV", "1.1.1.1,8.8.8.8"))
  ssh_authorized_keys    = split(",", get_env("TG_SSH_AUTH_KEYS_CSV", ""))
  ansible_user           = get_env("TG_ANSIBLE_USER", "ubuntu")
  enable_gpu_passthrough = tobool(get_env("TG_ENABLE_GPU_PASSTHROUGH", "false"))
  gpu_pci_address        = get_env("TG_GPU_PCI_ADDRESS", "")
  enable_tailscale_setup = tobool(get_env("TG_ENABLE_TAILSCALE", "true"))
  tailscale_tag          = "tag:${get_env("TG_NAME", "k3s-master-webapp")}"
  tailscale_auth_key     = get_env("TG_TAILSCALE_AUTH_KEY", "")
  enable_github_runner   = tobool(get_env("TG_ENABLE_GITHUB_RUNNER", "true"))
  github_runner_token    = get_env("TG_GITHUB_RUNNER_TOKEN", "")
  github_runner_labels   = get_env("TG_GITHUB_RUNNER_LABELS", "self-hosted,libvirt")
}
EOF
```

### Step 3: Create BWS Inventory

Create a new secret in Bitwarden Secrets Manager:

```
Secret Key: inventory/clientname-k3s-master-staging-webapp-latest
Value: <JSON inventory following schema v3>
```

See `inventory/schema/v3.json` for the complete schema.

### Step 4: Deploy

```bash
cd infra/terragrunt/live/clientname/staging/webapp

# Plan (dry-run)
terragrunt plan

# Apply
terragrunt apply
```

The root configuration will automatically:
- Create or select the `clientname` workspace in Terraform Cloud
- Use the GitHub-hosted module
- Store state in Terraform Cloud

## Benefits of This Pattern

### 1. DRY (Don't Repeat Yourself)

- **Before**: Backend config, module source, and common settings duplicated in every child config
- **After**: Common config defined once in root, inherited by all children

### 2. Consistency

- All environments use the same backend configuration
- Module version managed centrally
- Workspace naming logic standardized

### 3. Maintainability

- Update backend settings in one place (root config)
- Change module source or version globally
- Easy to add new environments

### 4. Scalability

- Directory structure scales naturally for multi-client/multi-environment
- Client-based workspaces group related infrastructure
- Clear separation between clients and environments

### 5. Security

- Secrets never committed to Git (all via environment variables)
- Terraform Cloud token management centralized
- State backend externally managed (prevents VM self-destruction)

## Migrating to Multi-Client Structure

When you're ready to adopt the multi-client directory structure:

### Step 1: Plan the Migration

1. Identify all current deployments
2. Map them to the new structure
3. Plan the state migration

### Step 2: Create New Directory Structure

```bash
mkdir -p infra/terragrunt/live/homelab/staging
mv infra/terragrunt/live/media-stack-single-node \
   infra/terragrunt/live/homelab/staging/media_stack
```

### Step 3: Update Child Config (if needed)

The child config should continue to work as-is since it already uses `find_in_parent_folders()`.

### Step 4: Test

```bash
cd infra/terragrunt/live/homelab/staging/media_stack
terragrunt plan
```

Verify that:
- Workspace is still `homelab`
- State is found correctly
- No changes are detected (infrastructure already exists)

### Step 5: Update Workflows

Update GitHub Actions workflows to reference the new directory structure.

## Troubleshooting

### Issue: Workspace not found

**Cause**: Terraform Cloud workspace doesn't exist for the client.

**Solution**: The workspace is auto-created on first `terragrunt init`. If manual creation is needed:
- Go to https://app.terraform.io/app/mightymorgs/workspaces
- Click "New workspace"
- Name it after the client (e.g., `homelab`, `austerit`)

### Issue: Module source not found

**Cause**: GitHub module reference is incorrect or inaccessible.

**Solution**:
1. Verify the module path exists: `infra/terraform/modules/k3s-vm-gpu/`
2. Check GitHub authentication (for private repos)
3. Override with local path for testing:
   ```bash
   export TG_MODULE_SOURCE="${PWD}/infra/terraform/modules/k3s-vm-gpu"
   ```

### Issue: Variables not being passed

**Cause**: Environment variables not set.

**Solution**: Ensure all required `TG_*` variables are exported:
```bash
export TG_NAME="homelab-k3s-master-staging-media_stack-latest"
export TG_VCPU="12"
export TF_CLOUD_TOKEN="<token>"
# ... etc
```

In CI/CD, these are automatically composed by GitHub Actions from BWS inventory.

### Issue: State migration needed

**Cause**: Moving from old backend (MinIO/PostgreSQL) to Terraform Cloud.

**Solution**: Terraform will prompt to migrate state automatically:
```bash
terragrunt init
# Answer "yes" when prompted to migrate state
```

## References

- **Terragrunt Documentation**: https://terragrunt.gruntwork.io/
- **Terraform Cloud**: https://app.terraform.io/
- **VM Naming Convention**: `docs/VM_NAMING_CONVENTION.md`
- **Architecture**: `docs/ARCHITECTURE.md`
- **BWS Integration**: `docs/BWS_TOKEN_USAGE.md`

## Support

For issues or questions:
- Open a GitHub issue
- Review the main architecture documentation: `docs/ARCHITECTURE.md`
- Check workflow logs in GitHub Actions for CI/CD issues
