# Risk log

Scores are High, Medium, or Low. I wrote this from the repository and from the two AWS sessions, not from a workshop. Owner is me.

| ID | Risk | Likelihood | Impact | What I do about it | Status |
| --- | --- | --- | --- | --- | --- |
| R1 | A proof-of-concept session runs overnight. NAT, EKS, and RDS bill the whole time. The 25 USD budget emails and does not stop spend. | Medium | High | `aws-poc.ps1` asks for `yes` and prints the hourly warning. Apply is manual. `down` is the last step of the session notes. | Open |
| R2 | Home IP changes. `MY_IP_CIDR` and `terraform.tfvars` disagree, and the EKS API allow list flips. | High | Medium | Update both in the same sitting. The script refuses to plan if tfvars is not the current address. | Open |
| R3 | Laptop and GitHub Actions both apply. The lock stops a crash. It does not stop two correct plans from undoing each other. | Medium | Medium | One writer per session. | Open |
| R4 | `grow-room-gha-apply` is `AdministratorAccess`. An approved job can do more than this stack. | Low | High | Documented as a demo shortcut. Not narrowed yet. | Open |
| R5 | The laptop sleeps. Live Grafana goes flat. I debug a scrape that is actually the lid. | High | Low | Written next to the dashboard and in Week 4. | Accepted |
| R6 | `HA_TOKEN` leaks from `.env` or a shell history. The token can read controller state. | Low | Medium | Gitignore `.env` and `ha-config/`. The token is not in the chart. | Open |
| R7 | `/metrics` on port 8000 has no authentication. The port is on the Docker host so k3d can scrape it. | Medium | Low | Do not publish that port past the house. No NetworkPolicy yet. | Open |
| R8 | Audit hash is recomputed by anyone who can write the database. The integrity check still passes. | Low | Medium | I say this when I demo the endpoint. No external anchor. | Accepted |
| R9 | k3d audit file is on `emptyDir`. A new pod drops the history. | Medium | Low | Documented. PVC example is not deployed. | Accepted |
| R10 | SNS subscription sits at `PendingConfirmation`. Alerts are dropped and the drill looks broken. | Medium | Medium | `up` warns. Confirm once. Do not subscribe again. | Mitigated in the script |
| R11 | Kyverno Audit does not stop an unsigned image. The 3 November report was `no signatures found` for the cosign 3 layout. | High, until a new image is checked | Medium | CI now signs with cosign 2.6.5 and the legacy tag. Enforce stays off until a PolicyReport passes. | Open |
| R12 | `TargetDown` for `grow-room-ha-host` on EKS, because that address is the laptop. | Medium | Low | `monitoring/values-eks.yaml` sets `additionalScrapeConfigs` to an empty list. | Mitigated in Git |
| R13 | `terraform destroy` hangs on an available network interface. | Medium | Medium | `down` deletes available interfaces in the proof-of-concept VPC before and during destroy. | Mitigated in the script |
| R14 | Telemetry KMS key is left up and forgotten. About 1 USD per month. | Medium | Low | `down` prints that the telemetry stack is kept. The Phase 3 page says how to think about deleting it. | Open |
| R15 | Cost Explorer cells stay blank, and the script's 0.70 USD figure gets quoted as a measurement. | Medium | Low | `COSTS.md` is still empty on purpose. Phase 6 says to fill it from the API. | Open |
| R16 | Grafana lab password and the state KMS key id are in Git. | High, they are in the files | Medium | I do not copy them into new pages. Rotating the lab password is a local change. The state key id moving would be a backend change. | Open |
| R17 | No Dependabot or Renovate. Pinned actions still go stale. | Medium | Low | On the roadmap, after the product work. | Open |
| R18 | Two Home Assistant copies log into AC Infinity at once. | Medium, during a move | Medium | `up -WithHA` and `down` refuse to start the second copy. The failure table is on the Phase 8 page. | Mitigated in the script |

I am not scoring a physical break-in or a stolen laptop beyond R6 and the Roles Anywhere key. Those need a different note than this log.
