# Network: VPC with public subnets for the load balancer and private subnets for
# ECS tasks and RDS, one NAT per AZ in prod, VPC endpoints for Secrets Manager,
# ECR and CloudWatch so tasks need no public egress for AWS APIs.
#
# TODO(phase-6): aws_vpc, aws_subnet (public/private per AZ), aws_nat_gateway,
# aws_route_table, aws_vpc_endpoint, security groups (alb -> ecs -> rds only).
locals {
  tags = {
    project     = "greenloop"
    environment = var.environment
    managed_by  = "terraform"
  }
}