variable "database_name" {
  type    = string
  default = "PROCUREPULSE"
}

variable "warehouse_name" {
  type    = string
  default = "PP_WH"
}

variable "monthly_credit_quota" {
  description = "Hard ceiling on credits per month. Trial credits are free; the monitor stops runaway cost if a card is ever added."
  type        = number
  default     = 5
}

variable "ci_user_public_key" {
  description = "RSA public key (PEM body without header/footer) of the CI service user. The private key lives only in GitHub secrets."
  type        = string
  sensitive   = true
}

variable "copilot_user_public_key" {
  description = "RSA public key of the read-only Process Copilot user. Leave empty to skip that user."
  type        = string
  default     = ""
  sensitive   = true
}
