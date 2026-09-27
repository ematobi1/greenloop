output "log_group_names" {
  description = "CloudWatch log groups this module will create."
  value       = [for service in var.services : "/${var.name}/${var.environment}/${service}"]
}