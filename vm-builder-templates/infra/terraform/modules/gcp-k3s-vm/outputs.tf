output "name" {
  description = "VM name"
  value       = var.name
}

output "instance_id" {
  description = "GCP instance ID"
  value       = google_compute_instance.vm.instance_id
}

output "self_link" {
  description = "GCP instance self link"
  value       = google_compute_instance.vm.self_link
}

output "internal_ip" {
  description = "Internal (private) IP address"
  value       = google_compute_instance.vm.network_interface[0].network_ip
}

output "external_ip" {
  description = "External (public) IP address (if enabled)"
  value       = var.enable_external_ip ? google_compute_instance.vm.network_interface[0].access_config[0].nat_ip : null
}

output "static_ip" {
  description = "Static external IP (if reserved)"
  value       = var.enable_static_ip ? google_compute_address.external[0].address : null
}

output "zone" {
  description = "Zone where instance is running"
  value       = google_compute_instance.vm.zone
}

output "machine_type" {
  description = "Machine type used"
  value       = var.machine_type
}

output "ssh_command" {
  description = "SSH command to connect to VM"
  value       = var.enable_external_ip ? "ssh ubuntu@${google_compute_instance.vm.network_interface[0].access_config[0].nat_ip}" : "ssh ubuntu@${google_compute_instance.vm.network_interface[0].network_ip}"
}

output "status" {
  description = "Instance status"
  value       = google_compute_instance.vm.current_status
}
