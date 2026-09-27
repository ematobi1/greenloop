# ECS on Fargate: one cluster, one service per entry in var.services behind an
# ALB (web public, orchestrator via /api, broker internal only). Task roles get
# read access to exactly the secrets each service needs; the broker is the only
# task that can read the GitHub App key.
#
# TODO(phase-6): aws_ecs_cluster, aws_ecs_task_definition, aws_ecs_service,
# aws_lb, aws_lb_target_group, aws_iam_role (per service), autoscaling.
locals {
  tags = {
    project     = "greenloop"
    environment = var.environment
    managed_by  = "terraform"
  }
}