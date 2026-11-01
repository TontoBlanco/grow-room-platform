# Pod Identity: each controller's Kubernetes service account gets its own IAM role.
module "lbc_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                            = "${local.name}-aws-lbc"
  attach_aws_lb_controller_policy = true
  associations = {
    this = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
    }
  }
}

module "eso_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                                  = "${local.name}-external-secrets"
  attach_external_secrets_policy        = true
  external_secrets_secrets_manager_arns = [aws_db_instance.audit.master_user_secret[0].secret_arn]
  external_secrets_kms_key_arns         = [module.kms_secrets.arn]
  external_secrets_create_permission    = false
  associations = {
    this = {
      cluster_name    = module.eks.cluster_name
      namespace       = "external-secrets"
      service_account = "external-secrets"
    }
  }
}

module "exporter_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                 = "${local.name}-sensor-exporter"
  attach_custom_policy = true
  policy_statements = [
    {
      sid       = "PutRawReadings"
      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.sensor.arn}/raw/*"]
    },
    {
      sid       = "UseDataKey"
      actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
      resources = [module.kms_s3.arn]
    }
  ]
  associations = {
    this = {
      cluster_name    = module.eks.cluster_name
      namespace       = "grow-room"
      service_account = "sensor-exporter"
    }
  }
}

# ExternalDNS: may only change records in your one hosted zone
module "external_dns_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                          = "${local.name}-external-dns"
  attach_external_dns_policy    = true
  external_dns_hosted_zone_arns = [data.aws_route53_zone.this.arn]
  associations = {
    this = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "external-dns"
    }
  }
}

# CloudWatch Container Insights add-on (with its own Pod Identity role)
module "cw_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"
  count   = var.enable_container_insights ? 1 : 0

  name                                       = "${local.name}-cloudwatch"
  attach_aws_cloudwatch_observability_policy = true
}

resource "aws_eks_addon" "cloudwatch" {
  count        = var.enable_container_insights ? 1 : 0
  cluster_name = module.eks.cluster_name
  addon_name   = "amazon-cloudwatch-observability"

  pod_identity_association {
    role_arn        = module.cw_pod_identity[0].iam_role_arn
    service_account = "cloudwatch-agent"
  }
}