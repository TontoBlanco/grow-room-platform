# GitHub Project setup

I want one project board for this repository and one milestone per phase. I checked on 3 November 2026.

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
gh project list --owner TontoBlanco --limit 20
```

That command returned no projects.

```powershell
gh api repos/TontoBlanco/grow-room-platform/milestones --jq ".[].title"
```

That command returned no milestones. I did not create the project or the milestones from this session. The GitHub CLI available here can read. It cannot create these resources. Run the commands below from your own login, in PowerShell, from `C:\src\grow-room-platform`.

## Project

```powershell
gh project create --owner TontoBlanco --title "Grow room platform"
```

The command prints a project number. Use that number anywhere the next command says the number. Link the repository:

```powershell
gh project link 1 --owner TontoBlanco --repo grow-room-platform
```

Replace `1` with the number `gh project create` printed. `--repo` is the repository name, and `--owner` is `TontoBlanco`.

The default Status field is enough. I am not adding a custom field until the board has cards.

## Milestones

One milestone per phase. Titles match the documentation pages. Descriptions say where the work lives. Completed phases stay open until I close them, so the list is complete first.

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Week 1: Application and CI" -f description="FastAPI service, tests, Docker image, GitHub Actions. See docs/phases/week-1-application-and-ci.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Week 2: Terraform for the local lab" -f description="infra/ modules and terraform.yml. No apply. See docs/phases/week-2-terraform.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Week 3: Kubernetes and GitOps" -f description="k3d grow-room-dev, Helm, Argo CD, gitops-bump. See docs/phases/week-3-gitops.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Week 4: Observability and the live tent" -f description="Prometheus, Grafana, job grow-room-ha-host. See docs/phases/week-4-observability.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Week 5: Audit history" -f description="SQLite by default, optional Postgres. See docs/phases/week-5-audit.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="AWS proof of concept" -f description="infra/aws-poc in us-west-2. Apply and destroy in one session. See docs/phases/aws-proof-of-concept.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 1: GitHub Actions OIDC" -f description="aws-poc plan, manual apply, manual destroy. See docs/phases/phase-1-oidc.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 2: Up, verify, and down" -f description="scripts/aws-poc.ps1. See docs/phases/phase-2-up-verify-down.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 3: Readings in S3 and Athena" -f description="infra/telemetry, ship_readings.py, sensor-exporter. See docs/phases/phase-3-telemetry.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 4: SLOs, alerts, and drills" -f description="SNS topic grow-room-poc-alerts and docs/aws-poc/DRILLS.md. See docs/phases/phase-4-slos-and-drills.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 5: Signing, SBOM, and the scan gate" -f description="Trivy, Syft, cosign 2.6.5, Kyverno Audit. See docs/phases/phase-5-supply-chain.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 6: Costs and decision records" -f description="docs/aws-poc/COSTS.md and docs/adr. See docs/phases/phase-6-costs-and-adrs.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 7: Ansible on WSL2" -f description="ansible/ roles base and k8s_tools. See docs/phases/phase-7-ansible.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Phase 8: Home Assistant backup and restore" -f description="Not built. S3 backup and restore between the house and a us-west-2 session. See docs/project-management/roadmap.md."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Growth stage VPD bands" -f description="Merged. Pull request 77, 3 November 2026. GROW_STAGE on main."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Roadmap: Athena in local Grafana" -f description="Not built. Workgroup grow-room-telemetry as a Grafana data source on k3d."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Roadmap: grow alerts the controller cannot see" -f description="Not built. Toggleable alerts that do not repeat AC Infinity."
```

```powershell
gh api --method POST repos/TontoBlanco/grow-room-platform/milestones -f title="Roadmap: Dependabot or Renovate" -f description="Not built. No dependabot.yml and no Renovate config in the repo."
```

Confirm:

```powershell
gh api repos/TontoBlanco/grow-room-platform/milestones --jq ".[].title"
```

Close a finished milestone only after you have looked at it. Example for Week 1, after you read the number from the list:

```powershell
gh api repos/TontoBlanco/grow-room-platform/milestones --jq ".[] | {number,title}"
```

```powershell
gh api --method PATCH repos/TontoBlanco/grow-room-platform/milestones/1 -f state="closed"
```

Replace `1` with the milestone number you intend to close. Do not close Phase 8 or the roadmap milestones. They are not done.
