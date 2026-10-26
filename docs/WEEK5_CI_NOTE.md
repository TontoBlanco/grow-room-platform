# Week 5 CI note

Do **not** copy a finished audit CI workflow from this pack into
`.github/workflows/`.

Week 5 deliverable is the **append-only audit API + docs/write-up scaffolding**.
Optional CI polish (you author it yourself when the module is merged):

1. **Audit unit tests** — ensure `pytest tests/test_audit.py` (or the whole
   suite) runs on PRs that touch `sensor_service/audit/` or `tests/test_audit.py`.
2. **Schema smoke** — a job step that opens a throwaway DB path and calls
   `AuditStore(...)._init_schema()` / create-batch once (catches broken SQL early).
3. **No secrets** — never commit `data/*.db` or real plant/batch production data;
   CI should use `AUDIT_DB_PATH=$RUNNER_TEMP/audit.db`.
4. **Keep Trivy** — image scan you already run in Week 1 CI still applies; Week 5
   compliance notes treat that as the SBOM-adjacent check you already have.

The repo's `.github/workflows/ci.yml` test job runs the whole suite, including
Postgres audit tests, against a `postgres:16` service container.
`AUDIT_TEST_DATABASE_URL` is set only for that step. When it is unset, those
tests skip and the SQLite path still runs. That container is GitHub-hosted CI.
It is not RDS.

Locally, `pytest` is enough without Postgres. Verify `/audit/integrity` by
hand when you want to see the chain.

See `docs/WEEK5_AUDIT_LOG_GUIDE.md` for the teaching path.
