<!-- docs/aws-poc/COSTS.md -->
# AWS PoC cost record

Every number in this file comes from Cost Explorer or the AWS bill.
No estimates are written as facts. Blank = not measured yet.

## How I measure

- Cost Explorer, region us-west-2, filter tag `Project = grow-room`, granularity Daily.
- The `Project` tag is activated as a cost allocation tag (Billing -> Cost allocation tags).
- CLI query used (see bottom). Cost Explorer data lags up to 24 hours.

## Sessions

| Date | Hours up | What I did | Total USD (Cost Explorer) | Notes |
|------|----------|------------|--------------------------|-------|
| 2026-11-01 | | First build + teardown | | |
| | | | | |

## Cost by service for one session

| Service | USD | Driver (what was running) |
|---------|-----|---------------------------|
| Amazon Elastic Kubernetes Service | | control plane hours |
| EC2 - Other (NAT gateway, EBS, data transfer) | | |
| Amazon EC2 (instances) | | node hours |
| Amazon RDS | | Multi-AZ instance hours |
| Elastic Load Balancing | | ALB hours + LCU |
| AWS WAF | | web ACL + rules, prorated |
| AWS Key Management Service | | keys prorated |
| Amazon CloudWatch | | Container Insights, logs |
| Other | | |

## Always-on (between sessions)

| Item | USD / month (from bill) |
|------|-------------------------|
| Route 53 hosted zone mygrowroom.click | |
| KMS key: tfstate | |
| KMS key: telemetry | |
| S3: state + telemetry | |

## What I learned

- Biggest line item:
- Cheapest change that would cut it:
- What I would pay in production instead:

## Query

```powershell
aws ce get-cost-and-usage --time-period Start=2026-11-01,End=2026-11-02 --granularity DAILY --metrics UnblendedCost --filter file://ce-filter.json --group-by Type=DIMENSION,Key=SERVICE
```