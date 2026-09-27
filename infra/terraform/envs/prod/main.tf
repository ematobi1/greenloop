# prod environment. Composes the modules; no provider or backend is configured
# yet, so nothing can be applied.
#
# TODO(phase-6): required_providers aws, an S3 backend with DynamoDB locking,
# and provider "aws" { region = var.aws_region, default_tags = ... }.

terraform {
  required_version = ">= 1.6"
}

locals {
  environment = "prod"
}

module "network" {
  source      = "../../modules/network"
  environment = local.environment
  vpc_cidr    = "10.41.0.0/16"
}

module "secrets" {
  source      = "../../modules/secrets"
  environment = local.environment
}

module "rds" {
  source              = "../../modules/rds"
  environment         = local.environment
  multi_az            = true
  deletion_protection = true
}

module "ecs" {
  source      = "../../modules/ecs"
  environment = local.environment
}

module "observability" {
  source             = "../../modules/observability"
  environment        = local.environment
  log_retention_days = 90
}