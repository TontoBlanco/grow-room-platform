"""FastAPI app: /healthz, /readings, /metrics."""

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from sensor_service import __version__
from sensor_service.config import build_source, leaf_offset_c
from sensor_service.sources import Source

# Own registry so tests can build multiple apps without duplicate-metric errors.
registry = CollectorRegistry()
TEMP_C = Gauge("grow_temperature_celsius", "Air temperature", registry=registry)
HUMIDITY = Gauge("grow_humidity_percent", "Relative humidity", registry=registry)
VPD = Gauge("grow_vpd_kpa", "Vapor pressure deficit", registry=registry)
CO2 = Gauge("grow_co2_ppm", "CO2 concentration", registry=registry)
READ_ERRORS = Counter("grow_read_errors", "Failed sensor reads", registry=registry)


def create_app(source: Source | None = None, leaf_offset: float | None = None) -> FastAPI:
    app = FastAPI(title="grow-room sensor service", version=__version__)
    src = source or build_source()
    offset = leaf_offset_c() if leaf_offset is None else leaf_offset

    def latest() -> dict:
        try:
            data = src.read().to_dict(offset)
        except Exception as exc:
            READ_ERRORS.inc()
            raise HTTPException(status_code=503, detail=f"sensor read failed: {exc}") from exc
        TEMP_C.set(data["temperature_c"])
        HUMIDITY.set(data["humidity_percent"])
        VPD.set(data["vpd_kpa"])
        if data["co2_ppm"] is not None:
            CO2.set(data["co2_ppm"])
        return data

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readings")
    def readings() -> dict:
        return latest()

    @app.get("/metrics")
    def metrics() -> Response:
        try:
            latest()  # refresh gauges on each scrape
        except HTTPException:
            pass  # still serve metrics; error counter shows the failure
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    from sensor_service.audit import create_audit_router

    app.include_router(create_audit_router())

    return app


app = create_app()
