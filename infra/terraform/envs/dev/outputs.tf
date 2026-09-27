output "services" {
  description = "ECS services planned for this environment."
  value       = module.ecs.service_names
}

output "secret_paths" {
  description = "Secrets Manager names the services will read."
  value       = module.secrets.secret_paths
}

output "log_groups" {
  description = "CloudWatch log groups planned for this environment."
  value       = module.observability.log_group_names
}