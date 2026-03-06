# Terragrunt configuration for Tailscale network management
# Manages ACL policy and device tags via Terraform Cloud backend

locals {
  tfc_workspace_name = "tailscale-config"
  tfc_organization   = get_env("TG_TFC_ORGANIZATION", "morgs-home-lab")
}

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
  }
}
EOF
}

generate "versions" {
  path      = "versions.tf"
  if_exists = "overwrite"
  contents  = <<EOF
terraform {
  required_version = ">= 1.0"
  required_providers {
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.17"
    }
  }
}
EOF
}

terraform {
  source = "../../../terraform/modules/tailscale-config"
}

inputs = {
  hypervisor_hostname = get_env("TG_HYPERVISOR_HOSTNAME", "k3s-austerit")
  hypervisor_tags     = split(",", get_env("TG_HYPERVISOR_TAGS", "tag:k3s-austerit,tag:vm-host,tag:service-ssh"))
}
