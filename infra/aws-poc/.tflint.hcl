# infra/aws-poc/.tflint.hcl
config {
  call_module_type = "local"   # lint modules/vpc and modules/kms-key too
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.43.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}