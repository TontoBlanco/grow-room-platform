# Week 5 write-up outline (architecture + blog)

Use this to draft the README architecture blurb and a short public post
(LinkedIn / personal blog / Dev.to). Publish when *you* are ready — publishing
is part of the canvas Definition of Done and cannot be automated from this pack.

---

## Architecture diagram (paste into README)

```mermaid
flowchart TB
  subgraph sources [Sensor inputs]
    HA[Home Assistant / AC Infinity]
    SIM[Simulator]
  end

  subgraph app [sensor-service FastAPI]
    READ[/readings /metrics]
    AUD[/audit API]
    FSM[Plant state FSM]
    STORE[(SQLite audit.db<br/>append-only events)]
  end

  subgraph platform [k3d GitOps lab]
    ARGO[Argo CD]
    PROM[Prometheus]
    GRAF[Grafana VPD]
  end

  HA --> READ
  SIM --> READ
  AUD --> FSM --> STORE
  READ --> PROM --> GRAF
  ARGO -->|Helm chart| app
```

One-sentence caption:

> Climate telemetry (Prometheus/Grafana) plus an append-only seed-to-sale style
> audit log (SQLite hash chain) on the same FastAPI service, delivered through
> GitOps on k3d at $0 cloud spend.

---

## README blurb (short)

```markdown
### Seed-to-sale audit log

Week 5 adds `/audit` — batches, plants, and append-only transition events with
a finite state machine and SHA-256 hash-chain integrity check. Default storage
is local SQLite (`AUDIT_DB_PATH`). This is a personal CEA portfolio model for
practicing compliance evidence patterns; it is not a licensed METRC client.
```

---

## Blog post outline (~800–1200 words)

**Title ideas**

- "Append-only plant audit logs on a $0 Kubernetes lab"
- "GitOps thinking applied to seed-to-sale style evidence"
- "From VPD dashboards to compliance trails in five weeks"

**Sections**

1. **Hook** — Home CEA grow + day-job Kubernetes habits; why evidence matters.
2. **What I built (Weeks 1–4 recap, 1 paragraph)** — FastAPI sensors, CI/GHCR,
   Terraform modules without reckless apply, Helm+Argo on k3d, Prometheus/Grafana.
3. **Week 5 problem** — Mutable "current state" is not enough for audits;
   need attribution + history + integrity.
4. **Design** — FSM, append-only events, hash chain, SQLite; mermaid diagram.
5. **K8s analogies** — admission webhooks, Git history vs live objects, Events.
6. **Security angle** — STIG-*style* checklist, Trivy already in CI, least
   privilege on the lab; explicitly not an ATO.
7. **What I skipped on purpose** — paid EKS/RDS, real METRC, Cosign (for now).
8. **What's next** — Terraform Associate exam; job applications in ag/cannabis
   tech; optional Pi edge.
9. **Close** — Link the GitHub repo; invite feedback.

**Tone**

- Professional, first person, specific.
- Legal personal hobby / CEA — no sales, no medical claims.
- No fabricated employer stories.

**Assets to attach**

- Grafana VPD screenshot (Week 4).
- `/docs` OpenAPI screenshot showing the `audit` tag.
- Mermaid diagram rendered.
- Link to `docs/WEEK5_AUDIT_LOG_GUIDE.md` in the repo after you push.

**Publish checklist**

- [ ] Draft in your editor
- [ ] Repo public + README roadmap checked for Week 5 when code is merged
- [ ] Proofread for overclaiming (METRC, STIG, ATO)
- [ ] Post + optional LinkedIn short pointing at the article
- [ ] Note the URL in your job-search tracker

---

## Exam / job-push companion (canvas done criteria)

Canvas: *Published write-up; exam booked or passed.*

| Item | Action |
|---|---|
| Write-up | Use this outline; publish |
| Terraform Associate | Book a Pearson/VUE slot; keep practicing with Week 2 modules |
| Job push | Tailor resume bullets to *this* portfolio only; ag/cannabis + platform roles |
