variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-2"
}

variable "project" {
  description = "Value of the Project tag on every resource."
  type        = string
  default     = "collar-telemetry"
}

variable "name_prefix" {
  description = "Prefix for resource names; matches the local moto run (src/cloud/local.py)."
  type        = string
  default     = "collar"
}

variable "alert_email" {
  description = "Address for likely_death alerts and the budget alarm. Set it in terraform.tfvars (git-ignored)."
  type        = string
}

variable "notify_enabled" {
  description = "Whether the notifier sends email. Off for bulk replays; on for the one deliberate test."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "AWS Budgets alarm threshold for the whole account, in US dollars."
  type        = number
  default     = 5
}

variable "processor_concurrency" {
  description = "Most processor instances the queue trigger runs at once. New accounts can have a 10-execution account limit, so leave room for the notifier."
  type        = number
  default     = 5
}

variable "lambda_zip" {
  description = "Deploy package built by `make lambda-zip`, relative to this directory."
  type        = string
  default     = "../../build/lambda.zip"
}
