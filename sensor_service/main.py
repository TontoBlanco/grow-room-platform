"""FastAPI app: /healthz, /readings, /mood, /stage, /metrics."""

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Info,
    generate_latest,
)

from sensor_service import __version__
from sensor_service.config import build_source, leaf_offset_c
from sensor_service.mood import BANDS, mood_for_vpd
from sensor_service.sources import Source
from sensor_service.stage import GrowthStage, load_growth_stage
from sensor_service.vpd import vpd_kpa

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
# Info metric: the sample is always 1. `stage` is GROW_STAGE (clone is stored
# as seedling). `display` is the grower-facing name. Targets are separate gauges
# so Grafana can draw the band without hard-coded thresholds.
GROW_ROOM_STAGE = Info(
    "grow_room_stage",
    "Configured plant growth stage for the leaf VPD target band",
    registry=registry,
)
VPD_TARGET_LOW = Gauge(
    "grow_vpd_target_low_kpa",
    "Lower edge of the growth-stage leaf VPD target band, kPa, inclusive",
    registry=registry,
)
VPD_TARGET_HIGH = Gauge(
    "grow_vpd_target_high_kpa",
    "Upper edge of the growth-stage leaf VPD target band, kPa, inclusive",
    registry=registry,
)
VPD_IN_BAND = Gauge(
    "grow_vpd_in_target_band",
    "1 when computed leaf VPD is inside the inclusive growth-stage target band, else 0",
    registry=registry,
)

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


def _publish_stage(stage: GrowthStage, vpd_kpa: float | None = None) -> None:
    """Refresh stage and target gauges. In-band waits for a real VPD sample."""
    GROW_ROOM_STAGE.info({"stage": stage.name, "display": stage.display})
    VPD_TARGET_LOW.set(stage.low_kpa)
    VPD_TARGET_HIGH.set(stage.high_kpa)
    if vpd_kpa is not None:
        VPD_IN_BAND.set(1.0 if stage.contains(vpd_kpa) else 0.0)


def _attach_stage(data: dict, stage: GrowthStage) -> dict:
    data["growth_stage"] = stage.name
    data["vpd_target_low_kpa"] = stage.low_kpa
    data["vpd_target_high_kpa"] = stage.high_kpa
    data["vpd_in_target_band"] = stage.contains(data["vpd_kpa"])
    return data


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
    # Air VPD from the probe's own temp/RH, with no leaf offset. The controller
    # reports its own VPD the same way. A leaf offset would look like drift.
    probe_temp = probe.get("temperature_c")
    probe_rh = probe.get("humidity_percent")
    if probe_temp is not None and probe_rh is not None:
        try:
            calculated = vpd_kpa(probe_temp, probe_rh, 0.0)
        except ValueError:
            calculated = None
        if calculated is not None:
            _optional_gauge(
                "grow_probe_calculated_vpd_kpa",
                "Air VPD calculated by sensor-service from probe temperature and humidity, kPa",
            ).set(calculated)

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


def create_app(
    source: Source | None = None,
    leaf_offset: float | None = None,
    growth_stage: GrowthStage | None = None,
) -> FastAPI:
    app = FastAPI(title="grow-room sensor service", version=__version__)
    src = source or build_source()
    offset = leaf_offset_c() if leaf_offset is None else leaf_offset
    stage = load_growth_stage() if growth_stage is None else growth_stage
    _publish_stage(stage)

    def latest() -> dict:
        try:
            data = src.read().to_dict(offset)
        except Exception as exc:
            READ_ERRORS.inc()
            raise HTTPException(status_code=503, detail=f"sensor read failed: {exc}") from exc
        _attach_stage(data, stage)
        _publish_metrics(data)
        _publish_stage(stage, data["vpd_kpa"])
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

    @app.get("/stage")
    def growth_stage_route() -> dict:
        """Configured growth stage and its leaf-VPD target band.

        Does not read the sensor. ``note`` records where the default bands came from.
        """
        _publish_stage(stage)
        return stage.to_api()

    @app.get("/metrics")
    def metrics() -> Response:
        # Stage is config, so the band stays up when the sensor read fails.
        _publish_stage(stage)
        try:
            latest()  # refresh gauges on each scrape
        except HTTPException:
            pass  # still serve metrics; error counter shows the failure
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    from sensor_service.audit import create_audit_router

    app.include_router(create_audit_router())

    return app


app = create_app()
