terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "test_vm" {
  source = "../../modules/gcp-k3s-vm"

  # GCP settings
  project_id   = var.project_id
  region       = var.region
  zone         = var.zone
  machine_type = var.machine_type

  # VM name (following k8s-platform naming convention)
  name = var.vm_name

  # SSH access - from variable (passed from workflow)
  ssh_authorized_keys = var.ssh_authorized_keys != [] ? var.ssh_authorized_keys : [
    file(pathexpand(var.ssh_public_key_path))
  ]

  # Optional: GitHub runner
  runner_token        = var.runner_token
  ssh_private_key_b64 = var.ssh_private_key_b64
  github_repo         = var.github_repo

  # Network settings
  enable_external_ip  = true
  enable_ssh_firewall = true
  ssh_source_ranges   = var.ssh_source_ranges
}
