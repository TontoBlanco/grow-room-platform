# Week 4 CI note

Do **not** copy a finished observability CI workflow from this pack into
`.github/workflows/`.

Week 4 deliverable is **Prometheus + Grafana + alerts on k3d via GitOps**.
Optional CI polish (you author it yourself when the stack feels boring):

1. **Dashboard JSON lint** — `jq empty monitoring/dashboards/*.json` on PRs that
   touch `monitoring/`.
2. **PromQL / rule dry-check** — `promtool check rules` against a rendered
   copy of `monitoring/alerts/grow-room-rules.yaml` (needs `promtool` in CI).
3. **No loop with gitops-bump** — keep `paths-ignore` (or path filters) so chart
   value bumps and monitoring-only docs do not fight each other.

Until then: merge monitoring manifests by PR, let Argo sync, verify targets by
hand. That is a valid Week 4 done state.

See `docs/WEEK4_OBSERVABILITY_GUIDE.md` for the teaching path.
