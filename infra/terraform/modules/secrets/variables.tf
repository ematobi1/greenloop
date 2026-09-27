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
variable "secret_names" {
  description = "Secret names to create (values are set outside Terraform)."
  type        = list(string)
  default = [
    "anthropic-api-key",
    "elevenlabs-api-key",
    "github-app-id",
    "github-app-private-key",
  ]

  validation {
    condition     = alltrue([for name in var.secret_names : can(regex("^[a-z0-9-]+$", name))])
    error_message = "secret names must be lowercase letters, digits and hyphens."
  }
}