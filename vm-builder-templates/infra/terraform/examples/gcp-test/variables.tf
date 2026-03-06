variable "project_id" {
  description = "GCP project ID (get from: gcloud projects list)"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "GCP machine type"
  type        = string
  default     = "e2-medium" # 2 vCPU, 4GB RAM - good for testing with free credits
}

variable "vm_name" {
  description = "VM name"
  type        = string
  default     = "test-k3s-vm"
}

variable "ssh_public_key_path" {
  description = "Path to your SSH public key (for local use)"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_authorized_keys" {
  description = "List of SSH public keys (for workflow use)"
  type        = list(string)
  default     = []
}

variable "ssh_source_ranges" {
  description = "IP ranges allowed for SSH (0.0.0.0/0 = anywhere)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# Optional GitHub runner variables
variable "runner_token" {
  description = "GitHub Actions runner token (optional)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ssh_private_key_b64" {
  description = "Base64-encoded SSH private key (optional)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository for runner"
  type        = string
  default     = "mightymorgs/k8s-platform-automation"
}
