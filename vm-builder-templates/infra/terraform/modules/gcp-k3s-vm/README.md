# GCP K3s VM Module

Terraform module for provisioning K3s-ready VMs on Google Cloud Platform using **$300 free credits**.

## Free Credits

- **$300 USD credits for 90 days** (new accounts)
- E2-medium (2 vCPU, 4GB RAM) = ~$24/month
- **Run 24/7 for entire MVP development** with free credits
- **12+ months** if you destroy VMs when not testing

## Quick Start

### 1. Setup GCP Authentication

```bash
# Install gcloud CLI
brew install google-cloud-sdk  # macOS
# OR: https://cloud.google.com/sdk/docs/install

# Login with your account
gcloud auth login me@example.local

# Set your project (use the one from GCP console)
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable compute.googleapis.com
gcloud services enable iam.googleapis.com

# Create application default credentials for Terraform
gcloud auth application-default login
```

### 2. Find Your Project ID

```bash
# List all projects
gcloud projects list

# Output will show:
# PROJECT_ID              NAME                PROJECT_NUMBER
# your-project-123456     My First Project    123456789012

# Set the project ID
export TF_VAR_project_id="your-project-123456"
```

### 3. Create Test VM

```hcl
# infra/terraform/examples/gcp-test/main.tf
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = "us-central1"
}

module "test_vm" {
  source = "../../modules/gcp-k3s-vm"

  project_id = var.project_id
  name       = "test-k3s-vm"
  region     = "us-central1"
  zone       = "us-central1-a"

  # Machine type (with free credits, go bigger!)
  machine_type = "e2-medium"  # 2 vCPU, 4GB RAM

  # SSH access
  ssh_authorized_keys = [
    file("~/.ssh/id_ed25519.pub")
  ]

  # GitHub runner (optional)
  runner_token          = var.runner_token
  ssh_private_key_b64   = var.ssh_private_key_b64
  github_repo           = "mightymorgs/k8s-platform-automation"
}

output "vm_ip" {
  value = module.test_vm.external_ip
}

output "ssh_command" {
  value = module.test_vm.ssh_command
}

variable "project_id" {
  type = string
}

variable "runner_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "ssh_private_key_b64" {
  type      = string
  sensitive = true
  default   = ""
}
```

### 4. Deploy

```bash
cd infra/terraform/examples/gcp-test

# Initialize
terraform init

# Plan
terraform plan -var="project_id=your-project-123456"

# Apply (VM ready in ~90 seconds)
terraform apply -var="project_id=your-project-123456"

# Get the IP
terraform output vm_ip

# SSH in
ssh ubuntu@<ip-address>
```

### 5. Destroy When Done

```bash
terraform destroy  # Stop using credits immediately
```

## Cost Tracking

Check your credit usage:

```bash
# View billing
gcloud billing accounts list
gcloud billing projects describe YOUR_PROJECT_ID

# Or visit: https://console.cloud.google.com/billing
```

## Machine Types & Costs

| Type | vCPU | RAM | Cost/mo | Credits Used (24/7) |
|------|------|-----|---------|---------------------|
| **e2-micro** | 0.25-2 | 1GB | $6.11 | Always free tier |
| **e2-small** | 0.5-2 | 2GB | $12.23 | 24 months |
| **e2-medium** | 2 | 4GB | $24.46 | **12 months** ← Recommended |
| e2-standard-2 | 2 | 8GB | $48.92 | 6 months |
| e2-standard-4 | 4 | 16GB | $97.84 | 3 months |

**With free credits, use e2-medium or bigger for best testing experience.**

## Variables

### Required
- `project_id` - GCP project ID
- `name` - VM hostname
- `ssh_authorized_keys` - List of SSH public keys

### Common Options
- `machine_type` - Instance size (default: `e2-medium`)
- `region` - GCP region (default: `us-central1`)
- `zone` - GCP zone (default: `us-central1-a`)
- `runner_token` - GitHub Actions ephemeral token
- `ssh_private_key_b64` - Base64-encoded deploy key

### Advanced
- `enable_static_ip` - Reserve static IP (€0.79/mo)
- `data_disk_size_gb` - Additional storage
- `enable_ssh_firewall` - Create SSH firewall rule
- `deletion_protection` - Prevent accidental deletion

## Outputs

- `external_ip` - Public IP address
- `internal_ip` - Private IP address
- `ssh_command` - Ready-to-use SSH command
- `instance_id` - GCP instance ID

## Regions & Zones

**Cheapest regions** (all same price, but US-central has best free tier):
- `us-central1` (Iowa) - **Best for free tier**
- `us-east1` (South Carolina)
- `us-west1` (Oregon)
- `europe-west1` (Belgium)

**Zones**: Append `-a`, `-b`, or `-c` (e.g., `us-central1-a`)

## Integration with Workflows

Same as libvirt/Hetzner - just change the module source:

```yaml
# .github/workflows/phase2-provision-vm-gcp.yml
- name: Set module source
  run: |
    export TG_MODULE_SOURCE="/tmp/tg/infra/terraform/modules/gcp-k3s-vm"
```

## Comparison: GCP vs Hetzner vs Libvirt

| Feature | Libvirt | Hetzner | GCP Free Tier |
|---------|---------|---------|---------------|
| **Cost** | Free (your iMac) | €0.55/day | **$0 (credits)** |
| **Access** | Need iMac | Any browser | Any browser |
| **Speed** | 5-10 min | 60 sec | **90 sec** |
| **Credits** | N/A | None | **$300 for 90 days** |
| **Post-credits** | Free | €4.15/mo | $24/mo |

## Next Steps

1. ✅ GCP account created (me@example.local)
2. ✅ GCP module built
3. ⬜ Get project ID: `gcloud projects list`
4. ⬜ Enable APIs: `gcloud services enable compute.googleapis.com`
5. ⬜ Test deployment: See Quick Start above
6. ⬜ Verify GitHub runner connects
7. ⬜ Run Phase 2.5 bootstrap

## Troubleshooting

### "Error: could not find default credentials"
```bash
gcloud auth application-default login
```

### "Error 403: Compute Engine API has not been used"
```bash
gcloud services enable compute.googleapis.com
```

### "Error: The resource 'projects/X' was not found"
```bash
# Check project ID
gcloud projects list
# Set correct project
gcloud config set project YOUR_PROJECT_ID
```

### Check VM logs
```bash
# Via gcloud
gcloud compute instances get-serial-port-output test-k3s-vm --zone us-central1-a

# Or SSH and check
ssh ubuntu@<ip>
sudo cat /var/log/startup-script.log
```

## License

Apache 2.0
