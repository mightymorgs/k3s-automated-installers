# NOTE: This file is overwritten during CI by rendering terragrunt.hcl.j2.
# This static version is kept for local development and documentation.
# Root Terragrunt configuration - DRY for all live environments

locals {
  repo_root        = get_repo_root()
  tfc_organization = get_env("TG_TFC_ORGANIZATION", "morgs-home-lab")

  # Use full VM name as TFC workspace to ensure each VM gets isolated state.
  # Previously used only the client prefix (first component), which caused
  # deploying VM-B to destroy VM-A when both shared the same client name.
  # VM naming (7 components): {client}-{vmtype}-{subtype}-{state}-{purpose}-{platform}-{version}
  # Examples:
  #   homelab-k3s-master-prod-mediastack-libvirt-latest   → workspace: homelab-k3s-master-prod-mediastack-libvirt-latest
  #   homelab-k3s-master-dev-crdextract-libvirt-latest    → workspace: homelab-k3s-master-dev-crdextract-libvirt-latest
  tfc_workspace_name = get_env("TG_NAME", "homelab-k3s-master-staging-mediastack-libvirt-latest")
}

# Common Terraform Cloud configuration
generate "backend" {
  path      = "backend.tf"
  if_exists = "overwrite"
  contents  = <<EOF
terraform {
  cloud {
    organization = "${local.tfc_organization}"
    workspaces {
      name = "${local.tfc_workspace_name}"
    }
    token = "${get_env("TF_CLOUD_TOKEN", "")}"
  }
}
EOF
}

# Common Terraform configuration
terraform {
  source = get_env(
    "TG_MODULE_SOURCE",
    "github.com/mightymorgs/media-stack//infra/terraform/modules/k3s-vm-gpu?ref=main"
  )
}

# Common inputs (can be overridden by child configs)
inputs = {
  # Add common variables here if needed
}
