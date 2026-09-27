output "secret_paths" {
  description = "Secrets Manager names the services will read."
  value       = [for name in var.secret_names : "${var.name}/${var.environment}/${name}"]
}