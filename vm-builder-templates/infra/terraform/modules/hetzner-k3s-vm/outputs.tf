output "name" {
  description = "VM name"
  value       = var.name
}

output "server_id" {
  description = "Hetzner Cloud server ID"
  value       = hcloud_server.vm.id
}

output "ipv4_address" {
  description = "Public IPv4 address assigned by Hetzner"
  value       = hcloud_server.vm.ipv4_address
}

output "ipv6_address" {
  description = "Public IPv6 address assigned by Hetzner"
  value       = hcloud_server.vm.ipv6_address
}

output "floating_ip" {
  description = "Floating IP address (if enabled)"
  value       = var.enable_floating_ip ? hcloud_floating_ip.public[0].ip_address : null
}

output "private_ip" {
  description = "Private IP address (if private network attached)"
  value       = var.private_network_id != null ? hcloud_server_network.private[0].ip : null
}

output "server_type" {
  description = "Server type used"
  value       = var.server_type
}

output "location" {
  description = "Datacenter location"
  value       = var.location
}

output "data_volume_id" {
  description = "Data volume ID (if created)"
  value       = var.data_volume_size_gb > 0 ? hcloud_volume.data[0].id : null
}

output "status" {
  description = "Server status"
  value       = hcloud_server.vm.status
}
