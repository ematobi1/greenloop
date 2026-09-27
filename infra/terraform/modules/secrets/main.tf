# Secrets Manager entries, one per name in var.secret_names. Terraform creates
# the containers only; values are set out of band (console or CLI) and never
# appear in tfvars, plans or state.
#
# TODO(phase-6): aws_secretsmanager_secret per name with a KMS key, resource
# policies granting read to the specific ECS task role that needs each one.
locals {
  tags = {
    project     = "greenloop"
    environment = var.environment
    managed_by  = "terraform"
  }
}