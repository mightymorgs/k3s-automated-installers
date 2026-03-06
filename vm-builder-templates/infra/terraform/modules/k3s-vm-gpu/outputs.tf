output "name" {
  description = "VM name"
  value       = var.name
}

output "ip_address" {
  description = "Static IP when configured; null when using DHCP"
  value       = var.static_ipv4_cidr != "" ? split("/", var.static_ipv4_cidr)[0] : null
}

output "vcpu" {
  description = "Number of vCPUs allocated"
  value       = var.vcpu
}

output "memory_mb" {
  description = "Memory allocated in MB"
  value       = var.memory_mb
}

output "gpu_passthrough_enabled" {
  description = "Whether GPU passthrough is enabled"
  value       = var.enable_gpu_passthrough
}

output "gpu_pci_address" {
  description = "GPU PCI address (if GPU passthrough enabled)"
  value       = var.enable_gpu_passthrough ? var.gpu_pci_address : null
}

output "usb_nic_passthrough_enabled" {
  description = "Whether USB 5GbE NIC passthrough is enabled"
  value       = var.enable_usb_nic_passthrough
}

output "usb_nic_ids" {
  description = "USB NIC vendor:product IDs (if USB NIC passthrough enabled)"
  value       = var.enable_usb_nic_passthrough ? "${var.usb_nic_vendor_id}:${var.usb_nic_product_id}" : null
}

output "domain_id" {
  description = "Libvirt domain ID (for use with virsh commands)"
  value       = libvirt_domain.vm.id
}

# Diagnostic outputs removed - var.runner_token is sensitive and can't be output
# Diagnostics moved to null_resource with local-exec instead
