output "database_name" {
  description = "Name of the application database."
  value       = var.name
}

output "engine_version" {
  description = "PostgreSQL major version."
  value       = var.engine_version
}