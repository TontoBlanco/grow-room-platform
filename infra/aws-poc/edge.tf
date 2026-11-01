# ---------- Route 53 zone (owned by bootstrap; looked up, never destroyed here) ----------
data "aws_route53_zone" "this" {
  name         = var.domain
  private_zone = false
}

# ---------- ACM certificate, proven via a DNS record in that zone ----------
resource "aws_acm_certificate" "app" {
  domain_name       = local.app_fqdn
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for o in aws_acm_certificate.app.domain_validation_options : o.domain_name => o
  }
  allow_overwrite = true # same CNAME comes back each session
  zone_id         = data.aws_route53_zone.this.zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# The A (alias) record app.mygrowroom.click -> ALB is written by ExternalDNS from the Ingress
# host, because the ALB is created by the LB controller, not Terraform.

# ---------- Optional: Route 53 health check on the public endpoint ----------
resource "aws_route53_health_check" "app" {
  count             = var.enable_health_check ? 1 : 0
  fqdn              = local.app_fqdn
  type              = "HTTPS"
  port              = 443
  resource_path     = "/healthz"
  request_interval  = 30
  failure_threshold = 3
  tags              = { Name = "${local.name}-healthz" }
}

# ---------- WAF in front of the ALB ----------
resource "aws_wafv2_web_acl" "alb" {
  count = var.enable_waf ? 1 : 0
  name  = "${local.name}-alb"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit"
    priority = 2
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 500 # requests per 5 min per IP
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-alb"
    sampled_requests_enabled   = true
  }
}