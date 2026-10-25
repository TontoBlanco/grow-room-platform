variable "name_prefix" {
  description = "Prefix for resource Name tags (e.g. grow-room-dev)."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
}

variable "az_count" {
  description = "Number of AZs to use for subnet pairs."
  type        = number
}

variable "enable_nat_gateway" {
  description = "When true, create one NAT Gateway in the first public subnet."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "Region (used to look up availability zones)."
  type        = string
}
