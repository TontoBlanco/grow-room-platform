# Mount the audit router into `sensor_service/main.py`

Do **not** replace your whole `main.py`. Add a small include after `create_app`
builds the FastAPI instance.

## Patch (commented)

```python
# --- Week 5: seed-to-sale audit log (optional mount) --------------------
# from sensor_service.audit import create_audit_router
#
# def create_app(...):
#     app = FastAPI(...)
#     ...
#     app.include_router(create_audit_router())
#     return app
# -----------------------------------------------------------------------
```

Concrete edit inside `create_app`, after the `/metrics` route and before
`return app`:

```python
    from sensor_service.audit import create_audit_router

    app.include_router(create_audit_router())
```

## Env

```bash
# optional; default is ./data/audit.db
export AUDIT_DB_PATH=./data/audit.db
mkdir -p data
```

Add `data/*.db` to `.gitignore` if not already covered. Keep `data/.gitkeep`
so the directory exists in Git.

## Smoke after mount

```bash
uvicorn sensor_service.main:app --reload
curl -s localhost:8000/audit/batches -X POST -H 'content-type: application/json' \
  -d '{"name":"tent-a","strain":"demo"}'
curl -s localhost:8000/docs   # look for the "audit" tag
```

## Packaging note

`pyproject.toml` already lists `packages = ["sensor_service"]`. Setuptools will
pick up the new `sensor_service/audit/` subpackage automatically as long as
`audit/__init__.py` exists. No new third-party dependencies — SQLite is stdlib.
