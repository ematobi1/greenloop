variable "name" {
  description = "Name prefix for every resource in this module."
  type        = string
  default     = "greenloop"
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}
variable "services" {
  description = "Services that get a log group."
  type        = list(string)
  default     = ["orchestrator", "broker", "web"]
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30

  validation {
    condition     = contains([7, 14, 30, 60, 90, 180, 365], var.log_retention_days)
    error_message = "log_retention_days must be one of 7, 14, 30, 60, 90, 180, 365."
  }
}

variable "otel_enabled" {
  description = "Run the OpenTelemetry collector sidecar."
  type        = bool
  default     = true
}