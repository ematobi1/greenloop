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
  description = "Container services to run, keyed by service name."
  type = map(object({
    port     = number
    cpu      = number
    memory   = number
    internal = bool
  }))
  default = {
    orchestrator = { port = 8000, cpu = 512, memory = 1024, internal = false }
    broker       = { port = 8100, cpu = 256, memory = 512, internal = true }
    web          = { port = 3000, cpu = 256, memory = 512, internal = false }
  }
}