variable "region" {
  type    = string
  default = "us-west-2"
}

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "kubernetes_version" {
  type    = string
  default = "1.36" # 1.37 is also in standard support; 1.36 has more add-on mileage
}

variable "my_ip_cidr" {
  description = "Your home public IP as /32, e.g. 203.0.113.7/32 (PowerShell: (Invoke-RestMethod https://checkip.amazonaws.com).Trim() + '/32')"
  type        = string
}

variable "admin_principal_arn" {
  description = "FULL IAM role ARN, including the aws-reserved/sso.amazonaws.com/ path, that gets EKS cluster admin"
  type        = string
  default     = "arn:aws:iam::590183769702:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_aace36a5554414e5"
}

variable "domain" {
  description = "The Route 53 zone from bootstrap, e.g. mygrowroom.click"
  type        = string
}

variable "app_subdomain" {
  description = "App host becomes <app_subdomain>.<domain>"
  type        = string
  default     = "app"
}

variable "enable_health_check" {
  description = "Route 53 HTTPS health check on /healthz (small monthly fee)"
  type        = bool
  default     = false
}

variable "enable_waf" {
  type    = bool
  default = true
}

variable "enable_container_insights" {
  type    = bool
  default = true
}

variable "alert_email" {
  description = "Email address subscribed to the grow-room-poc-alerts SNS topic"
  type        = string
  default     = ""
}

variable "enable_ha_migration" {
  description = "Phase 8 only. Create the EBS CSI addon, node volume permissions, and the Home Assistant pod identity association. Leave false so a plain up plan does not add them. scripts/aws-poc.ps1 passes true only with -WithHA."
  type        = bool
  default     = false
}