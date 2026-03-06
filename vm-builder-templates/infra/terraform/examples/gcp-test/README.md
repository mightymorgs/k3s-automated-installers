# GCP Test VM - Quick Start

Test the GCP module with your $300 free credits.

## Setup (5 minutes)

### 1. Install gcloud CLI

```bash
# macOS
brew install google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Verify
gcloud --version
```

### 2. Authenticate

```bash
# Login
gcloud auth login

# Create application credentials for Terraform
gcloud auth application-default login
```

### 3. Get Your Project ID

```bash
# List projects
gcloud projects list

# You'll see output like:
# PROJECT_ID              NAME                PROJECT_NUMBER
# my-project-123456       My First Project    123456789012

# Copy the PROJECT_ID (first column)
```

### 4. Enable Required APIs

```bash
# Replace with your project ID
export PROJECT_ID="your-project-id"

# Enable Compute Engine API
gcloud services enable compute.googleapis.com --project=$PROJECT_ID

# Verify
gcloud services list --enabled --project=$PROJECT_ID | grep compute
```

## Deploy Test VM

### 1. Create terraform.tfvars

```bash
cat > terraform.tfvars <<EOF
project_id = "your-project-id"  # Replace with your project ID
vm_name    = "test-k3s-vm"
region     = "us-central1"
zone       = "us-central1-a"
EOF
```

### 2. Deploy

```bash
# Initialize Terraform
terraform init

# Plan (review what will be created)
terraform plan

# Apply (creates VM in ~90 seconds)
terraform apply

# Get outputs
terraform output
```

### 3. Connect

```bash
# SSH to the VM
ssh ubuntu@$(terraform output -raw external_ip)

# Check startup script logs
sudo cat /var/log/startup-script.log

# Verify Tailscale is installed
tailscale version
```

## Cost Tracking

```bash
# Check your billing (should show credits being used)
gcloud billing projects describe $PROJECT_ID

# Or visit: https://console.cloud.google.com/billing
```

## Cleanup

```bash
# Destroy VM (stops using credits immediately)
terraform destroy

# Verify it's gone
gcloud compute instances list --project=$PROJECT_ID
```

## What This Costs

With **$300 free credits**:

| Scenario | Daily Cost | Days Until Credits Expire |
|----------|------------|---------------------------|
| e2-medium 24/7 | $0.80 | **375 days** |
| e2-medium 8h/day | $0.27 | **1,111 days** |
| Destroy nightly (8h) | $0.27 | **Never (have $300)** |

**TL;DR**: You can run this 24/7 for **over a year** with free credits.

## Troubleshooting

### "Error: could not find default credentials"
```bash
gcloud auth application-default login
```

### "API has not been used in project"
```bash
gcloud services enable compute.googleapis.com --project=$PROJECT_ID
```

### "Permission denied (publickey)"
- Check your SSH key exists: `ls ~/.ssh/id_ed25519.pub`
- If not, create one: `ssh-keygen -t ed25519 -C "me@example.local"`

### Check VM status
```bash
# Via gcloud
gcloud compute instances list --project=$PROJECT_ID

# Get serial console output (see boot logs)
gcloud compute instances get-serial-port-output test-k3s-vm \
  --zone=us-central1-a \
  --project=$PROJECT_ID
```

## Next Steps

Once the VM is working:

1. Test GitHub Actions runner connection
2. Run Phase 2.5 bootstrap playbook
3. Deploy K3s cluster
4. Test media stack deployment

This validates the entire platform before building more automation.
