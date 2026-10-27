"""FastAPI app: /healthz, /readings, /mood, /metrics."""

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
from sensor_service.mood import BANDS, mood_for_vpd
from sensor_service.sources import Source

# Own registry so tests can build multiple apps without duplicate-metric errors.
registry = CollectorRegistry()
TEMP_C = Gauge("grow_temperature_celsius", "Air temperature", registry=registry)
HUMIDITY = Gauge("grow_humidity_percent", "Relative humidity", registry=registry)
VPD = Gauge("grow_vpd_kpa", "Vapor pressure deficit", registry=registry)
# Category code, not a quality ranking. Inactive bands are 0 so max() is current.
PLANT_MOOD = Gauge(
    "grow_room_plant_mood",
    (
        "Plant mood category from leaf VPD "
        "(1 stressful humid, 2 muggy, 3 ideal, 4 too dry, 5 stressful dry). "
        "Inactive bands are 0. Soft heuristic, not agronomy advice."
    ),
    ["band"],
    registry=registry,
)
CO2 = Gauge("grow_co2_ppm", "CO2 concentration", registry=registry)
READ_ERRORS = Counter("grow_read_errors", "Failed sensor reads", registry=registry)

# Created on first real sample so the simulator does not export a misleading 0.
_OPTIONAL_GAUGES: dict[str, Gauge] = {}


def _optional_gauge(name: str, documentation: str, *labelnames: str) -> Gauge:
    gauge = _OPTIONAL_GAUGES.get(name)
    if gauge is None:
        gauge = Gauge(name, documentation, labelnames=labelnames, registry=registry)
        _OPTIONAL_GAUGES[name] = gauge
    return gauge


def _set_labeled(name: str, documentation: str, label: str, value: float) -> None:
    _optional_gauge(name, documentation, "device").labels(device=label).set(value)


def _publish_metrics(data: dict) -> None:
    """Refresh Prometheus gauges from one /readings payload."""
    TEMP_C.set(data["temperature_c"])
    HUMIDITY.set(data["humidity_percent"])
    VPD.set(data["vpd_kpa"])
    if data["co2_ppm"] is not None:
        CO2.set(data["co2_ppm"])

    controller = data.get("controller") or {}
    if controller.get("vpd_kpa") is not None:
        _optional_gauge(
            "grow_controller_vpd_kpa",
            "Controller VPD reported by Home Assistant, converted to kPa",
        ).set(controller["vpd_kpa"])
    if controller.get("status") in ("on", "off"):
        _optional_gauge(
            "grow_controller_status",
            "1 if the controller status binary sensor is on, else 0",
        ).set(1.0 if controller["status"] == "on" else 0.0)

    probe = data.get("probe") or {}
    if probe.get("temperature_c") is not None:
        _optional_gauge(
            "grow_probe_temperature_celsius",
            "Internal probe temperature",
        ).set(probe["temperature_c"])
    if probe.get("humidity_percent") is not None:
        _optional_gauge(
            "grow_probe_humidity_percent",
            "Internal probe relative humidity",
        ).set(probe["humidity_percent"])
    if probe.get("vpd_kpa") is not None:
        _optional_gauge(
            "grow_probe_vpd_kpa",
            "Internal probe VPD reported by Home Assistant, converted to kPa",
        ).set(probe["vpd_kpa"])

    for device, port in (data.get("ports") or {}).items():
        power = port.get("current_power")
        if power is not None:
            _set_labeled(
                "grow_port_current_power",
                "Current UIS device power or speed level",
                device,
                power,
            )
        if port.get("status") in ("on", "off"):
            _set_labeled(
                "grow_port_status",
                "1 if the UIS device status binary sensor is on, else 0",
                device,
                1.0 if port["status"] == "on" else 0.0,
            )

    current = mood_for_vpd(data["vpd_kpa"])
    for band in BANDS:
        PLANT_MOOD.labels(band=band.band).set(band.score if band is current else 0)


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
        _publish_metrics(data)
        return data

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readings")
    def readings() -> dict:
        return latest()

    @app.get("/mood")
    def mood() -> dict:
        """Playful plant mood from the current leaf VPD.

        Soft heuristic for a mixed tent, not agronomy advice.
        """
        data = latest()
        current = mood_for_vpd(data["vpd_kpa"])
        return current.to_dict(
            vpd_kpa=data["vpd_kpa"],
            temperature_c=data["temperature_c"],
            humidity_percent=data["humidity_percent"],
        )

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
