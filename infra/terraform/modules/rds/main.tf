# RDS PostgreSQL 16 with pgvector, in private subnets, encrypted at rest,
# IAM auth enabled, automated backups, deletion protection in prod. The master
# password is generated and stored by RDS in Secrets Manager, never in state.
#
# TODO(phase-6): aws_db_subnet_group, aws_db_parameter_group, aws_db_instance
# (manage_master_user_password = true), CloudWatch alarms.
locals {
  tags = {
    project     = "greenloop"
    environment = var.environment
    managed_by  = "terraform"
  }
}