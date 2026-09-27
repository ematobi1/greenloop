output "service_names" {
  description = "Names of the ECS services this module will create."
  value       = sort(keys(var.services))
}

output "internal_services" {
  description = "Services reachable only inside the VPC."
  value       = sort([for name, service in var.services : name if service.internal])
}