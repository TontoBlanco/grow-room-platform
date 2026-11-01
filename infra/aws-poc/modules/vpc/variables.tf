variable "name" { type = string }
variable "cidr" { type = string }
variable "region" { type = string }
variable "cluster_name" { type = string }
variable "az_count" {
  type    = number
  default = 3
}
variable "flow_log_retention_days" {
  type    = number
  default = 1
}
variable "flow_log_kms_key_arn" {
  description = "CMK for the flow-log group; its key policy must allow logs.<region>.amazonaws.com"
  type        = string
  default     = null
}