# Observability: CloudWatch log groups per service, an OpenTelemetry collector
# sidecar exporting traces and metrics, and alarms on error rate, approval
# latency and broker denials.
#
# TODO(phase-6): aws_cloudwatch_log_group per service, ADOT collector config,
# aws_cloudwatch_metric_alarm, dashboards.
locals {
  tags = {
    project     = "greenloop"
    environment = var.environment
    managed_by  = "terraform"
  }
}