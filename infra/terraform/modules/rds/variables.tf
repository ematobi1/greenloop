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
variable "engine_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "allocated_storage_gb" {
  description = "Initial storage in GB."
  type        = number
  default     = 20
}

variable "multi_az" {
  description = "Run a standby in a second AZ."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Block deletion of the instance."
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "Days to keep automated backups."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 1 and 35."
  }
}