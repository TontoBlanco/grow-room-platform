# Week 2 CI note

Do **not** copy a finished `terraform.yml` from this pack into `.github/workflows/`.

Write your own workflow using `docs/WEEK2_TERRAFORM_GUIDE.md` Step 6.
A reference sample sits at the **bottom** of that guide (same pattern as Week 1).

Suggested checks: `terraform fmt -check`, `terraform init -backend=false` +
`validate`, and `tflint`. Leave `plan`/`apply` for later when AWS OIDC exists.
