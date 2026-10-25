variable "name_prefix" {
  description = "Prefix for resource naming (e.g. grow-room-dev)."
  type        = string
}

variable "cluster_mode" {
  description = "local (k3d/kind outputs only) or eks (IAM + security group stubs)."
  type        = string

  validation {
    condition     = contains(["local", "eks"], var.cluster_mode)
    error_message = "cluster_mode must be \"local\" or \"eks\"."
  }
}

variable "vpc_id" {
  description = "VPC ID from the network module (used when cluster_mode=eks)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (documented for future EKS node groups)."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Public subnet IDs (documented for future load balancers)."
  type        = list(string)
  default     = []
}

variable "kubernetes_version" {
  description = "Target Kubernetes version."
  type        = string
  default     = "1.31"
}
