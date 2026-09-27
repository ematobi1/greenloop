output "name_prefix" {
  description = "Prefix used for network resource names."
  value       = "${var.name}-${var.environment}"
}

output "vpc_cidr" {
  description = "CIDR block the VPC will use."
  value       = var.vpc_cidr
}

output "tags" {
  description = "Common tags applied to network resources."
  value       = local.tags
}