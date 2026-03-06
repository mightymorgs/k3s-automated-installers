terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

locals {
  # Extract IP from CIDR if provided
  static_ip = var.static_ipv4_cidr != "" ? split("/", var.static_ipv4_cidr)[0] : null

  # Startup script - same cloud-init approach as libvirt/hetzner
  startup_script = templatefile("${path.module}/templates/startup-script.sh.tpl", {
    vm_name               = var.name
    ssh_private_key_b64   = var.ssh_private_key_b64
    runner_token          = var.runner_token
    github_repo           = var.github_repo
    github_runner_version = var.github_runner_version
    ssh_authorized_keys   = var.ssh_authorized_keys
    bws_access_token      = var.bws_access_token
    inventory_key         = var.inventory_key
  })

  # Labels for organization (GCP requires lowercase, no underscores)
  labels = {
    client     = lower(replace(split("-", var.name)[0], "_", "-"))
    purpose    = lower(replace(var.purpose, "_", "-"))
    managed_by = "terraform"
    project    = "k8s-platform"
  }
}

# VPC Network (or use default)
data "google_compute_network" "vpc" {
  name = var.network_name
}

data "google_compute_subnetwork" "subnet" {
  name   = var.subnet_name
  region = var.region
}

# Static external IP (optional)
resource "google_compute_address" "external" {
  count  = var.enable_static_ip ? 1 : 0
  name   = "${var.name}-external-ip"
  region = var.region

  labels = local.labels
}

# Firewall rule for SSH (if needed)
# Note: Uses timeouts to handle eventual consistency and create_before_destroy
# to prevent issues when firewall rule already exists from previous runs
resource "google_compute_firewall" "ssh" {
  count   = var.enable_ssh_firewall ? 1 : 0
  name    = "${var.name}-allow-ssh"
  network = data.google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # Restrict to Tailscale CGNAT range + your IP
  source_ranges = concat(
    ["100.64.0.0/10"],  # Tailscale CGNAT
    var.ssh_source_ranges
  )

  target_tags = ["${var.name}-ssh"]

  # Handle re-creation gracefully
  lifecycle {
    create_before_destroy = true
  }

  timeouts {
    create = "5m"
    delete = "5m"
  }
}

# Compute Instance
resource "google_compute_instance" "vm" {
  name         = var.name
  machine_type = var.machine_type
  zone         = var.zone

  # Enable deletion protection for production
  deletion_protection = var.deletion_protection

  tags = concat(
    ["k3s-vm", var.purpose],
    var.enable_ssh_firewall ? ["${var.name}-ssh"] : []
  )

  labels = local.labels

  boot_disk {
    initialize_params {
      image = var.boot_disk_image
      size  = var.boot_disk_size_gb
      type  = var.boot_disk_type
    }
  }

  # Optional data disk
  dynamic "attached_disk" {
    for_each = var.data_disk_size_gb > 0 ? [1] : []
    content {
      source      = google_compute_disk.data[0].id
      device_name = "data"
      mode        = "READ_WRITE"
    }
  }

  network_interface {
    network    = data.google_compute_network.vpc.name
    subnetwork = data.google_compute_subnetwork.subnet.name

    # External IP configuration
    dynamic "access_config" {
      for_each = var.enable_external_ip ? [1] : []
      content {
        nat_ip = var.enable_static_ip ? google_compute_address.external[0].address : null
      }
    }
  }

  # Startup script for bootstrapping
  metadata = {
    startup-script = local.startup_script
    ssh-keys       = join("\n", [for key in var.ssh_authorized_keys : "ubuntu:${key}"])
  }

  metadata_startup_script = local.startup_script

  # Service account for GCP API access (optional)
  service_account {
    email  = var.service_account_email
    scopes = var.service_account_scopes
  }

  # Allow stopping for maintenance
  allow_stopping_for_update = true

  lifecycle {
    precondition {
      condition     = var.runner_token != "" || length(var.ssh_authorized_keys) > 0
      error_message = "Either runner_token or ssh_authorized_keys must be provided."
    }
  }
}

# Data disk (optional)
resource "google_compute_disk" "data" {
  count = var.data_disk_size_gb > 0 ? 1 : 0
  name  = "${var.name}-data"
  type  = var.data_disk_type
  zone  = var.zone
  size  = var.data_disk_size_gb

  labels = local.labels
}
