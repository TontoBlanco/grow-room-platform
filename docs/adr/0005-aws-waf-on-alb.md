<!-- docs/adr/0005-aws-waf-on-alb.md -->
# ADR-0005: AWS WAF on the ALB

- Status: Accepted
- Date: 2026-11-01

## Context
The app is internet-facing. Bots and common exploits hit any public endpoint.

## Decision
A regional web ACL with AWS managed rule groups (common rules, known bad inputs, IP reputation)
plus a rate-based rule, attached to the ALB.

## Alternatives considered
| Option | Why not |
|--------|---------|
| Security groups only | Layer 4: cannot inspect HTTP paths, headers, SQL injection |
| CloudFront + WAF | Better for global users and caching; not needed for one-region demo |
| Shield Advanced | 3,000 USD/month; Shield Standard is already free on the ALB |

## Consequences
Good: Layer 7 filtering, rate limiting, sampled request logs.
Bad: monthly web ACL + rule charges (prorated); false positives possible.

## SAA exam tie-in
WAF attaches to ALB, API Gateway, CloudFront, AppSync, Cognito. NOT to NLB.
Security groups = stateful L4; NACLs = stateless subnet L4; WAF = L7.