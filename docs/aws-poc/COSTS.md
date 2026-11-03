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
| 2026-11-01 | | First build + teardown | | Gallery day. Console month-to-date at capture was not the session cost. |
| 2026-11-03 | | Paid test session: verify, alerts, exporter, drills 1–4, teardown | | Passed. Teardown was clean. Dollar total not entered yet. |

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
| KMS key: telemetry | about 1 USD / month, from the telemetry stack comment, not from this table's Cost Explorer cells |
| S3: state + telemetry | small at this volume; not measured here |

The persistent telemetry stack (`infra/telemetry`) is the about 1 USD per
month line. It is not part of a session's hourly cost, and `down` does not
remove it. Phases 3 through 7 are done. The 3 November session is written
up on the [test session page](../test-session/2026-11-03.md). I still do
not fill a blank cell with a number I have not read from Cost Explorer.

## What I learned

- Biggest line item:
- Cheapest change that would cut it:
- What I would pay in production instead:

## Query

```powershell
aws ce get-cost-and-usage --time-period Start=2026-11-01,End=2026-11-02 --granularity DAILY --metrics UnblendedCost --filter file://ce-filter.json --group-by Type=DIMENSION,Key=SERVICE
```