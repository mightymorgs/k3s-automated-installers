output "vm_name" {
  description = "VM name"
  value       = module.test_vm.name
}

output "external_ip" {
  description = "External IP address"
  value       = module.test_vm.external_ip
}

output "internal_ip" {
  description = "Internal IP address"
  value       = module.test_vm.internal_ip
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = module.test_vm.ssh_command
}

output "instance_id" {
  description = "GCP instance ID"
  value       = module.test_vm.instance_id
}

output "zone" {
  description = "Zone where VM is running"
  value       = module.test_vm.zone
}
