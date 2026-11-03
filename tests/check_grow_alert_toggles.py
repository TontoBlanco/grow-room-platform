#!/usr/bin/env python3
"""Render charts/grow-alerts and prove each toggle is absent until enabled.

The pytest suite calls this when helm is on PATH. CI's helm job runs it
directly with REQUIRE_HELM=1 so a missing binary fails the build.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "grow-alerts"
SCRIPT = ROOT / "scripts" / "grow_alerts.py"

EMAIL_SETS = [
    "delivery.email.enabled=true",
    "delivery.email.to=you@example.com",
    "delivery.email.from=grow@example.com",
    "delivery.email.smarthost=smtp.example.com:587",
    "delivery.email.authUsername=you@example.com",
    "delivery.email.existingSecret=grow-alerts-smtp",
]


def helm_bin() -> str:
    return os.environ.get("HELM", "helm")


def template(sets: list[str], files: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [helm_bin(), "template", "grow-alerts", str(CHART), "-n", "monitoring"]
    for path in files or []:
        command.extend(["-f", path])
    for item in sets:
        command.extend(["--set", item])
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def documents(text: str) -> list[tuple[str, str]]:
    found = []
    for part in re.split(r"(?m)^---\s*$", text):
        kind = re.search(r"(?m)^kind:\s*(\S+)", part)
        if kind is None:
            continue
        name = re.search(r"(?m)^  name:\s*(\S+)", part)
        found.append((kind.group(1), name.group(1) if name else ""))
    return found


def assert_render(
    sets: list[str],
    expected: list[tuple[str, str]],
    files: list[str] | None = None,
) -> str:
    result = template(sets, files)
    if result.returncode != 0:
        raise SystemExit(result.stderr)
    found = documents(result.stdout)
    if found != expected:
        raise SystemExit(f"sets {sets}\nexpected {expected}\nfound {found}\n{result.stdout[:500]}")
    return result.stdout


def check() -> None:
    binary = helm_bin()
    if subprocess.run([binary, "version"], capture_output=True).returncode != 0:  # noqa: S603
        if os.environ.get("REQUIRE_HELM") == "1":
            raise SystemExit(f"helm is required ({binary})")
        print("helm not installed; skip grow-alert toggle render")
        return

    defaults = (CHART / "values.yaml").read_text(encoding="utf-8")
    if "enabled: true" in defaults:
        raise SystemExit("charts/grow-alerts/values.yaml must keep every alert off")
    assert_render([], [])

    k3d_files = [str(CHART / "values.yaml"), str(CHART / "values-k3d.yaml")]
    k3d = assert_render([], [("PrometheusRule", "grow-probe-drift")], files=k3d_files)
    for absent in (
        "GrowShipperStale",
        "GrowVpdOutOfBand",
        "GrowCertExpiring",
        "emailConfigs",
        "CronJob",
        "kind: Deployment",
        "kind: ConfigMap",
    ):
        if absent in k3d:
            raise SystemExit(f"k3d overlay render included {absent}")
    if "alert: GrowProbeDrift" not in k3d:
        raise SystemExit("k3d overlay did not render GrowProbeDrift")

    probe = assert_render(
        ["alerts.probeDrift.enabled=true"],
        [("PrometheusRule", "grow-probe-drift")],
    )
    for absent in (
        "GrowShipperStale",
        "GrowVpdOutOfBand",
        "GrowCertExpiring",
        "emailConfigs",
        "CronJob",
    ):
        if absent in probe:
            raise SystemExit(f"probe-only render included {absent}")
    for present in (
        "grow_probe_calculated_vpd_kpa",
        "grow_controller_vpd_kpa",
        'sensor_source="homeassistant"',
        "> 0.15",
        'for: "1h"',
        'grow_alert: "true"',
    ):
        if present not in probe:
            raise SystemExit(f"probe rule missing {present}")

    stale = assert_render(
        ["alerts.staleShipper.enabled=true"],
        [
            ("ConfigMap", "grow-alerts-script"),
            ("Service", "grow-alerts-credentials"),
            ("Deployment", "grow-alerts-credentials"),
            ("CronJob", "grow-shipper-stale"),
        ],
    )
    for present in (
        "grow_alerts.py shipper",
        "grow-room-telemetry-590183769702",
        '--minutes "30"',
        '--prefix "readings/"',
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        if present not in stale:
            raise SystemExit(f"shipper render missing {present}")
    if "PrometheusRule" in stale or "emailConfigs" in stale:
        raise SystemExit("shipper render included a rule or email config")

    vpd = assert_render(
        ["alerts.vpdOutOfBand.enabled=true"],
        [
            ("ConfigMap", "grow-alerts-script"),
            ("Service", "grow-alerts-credentials"),
            ("Deployment", "grow-alerts-credentials"),
            ("CronJob", "grow-vpd-day"),
        ],
    )
    for present in (
        "grow_alerts.py vpd-day",
        '--lookback-days "1"',
        '--outside-share "0.6"',
        '--workgroup "grow-room-telemetry"',
        '--database "grow_room_telemetry"',
        '--table "readings"',
    ):
        if present not in vpd:
            raise SystemExit(f"vpd render missing {present}")
    if "interval" in vpd.split("grow_alerts.py.b64", 1)[0]:
        raise SystemExit("vpd command mentioned an interval scan")

    certs = assert_render(
        ["alerts.certExpiry.enabled=true"],
        [
            ("ConfigMap", "grow-alerts-script"),
            ("CronJob", "grow-cert-expiry"),
        ],
    )
    for present in ("2027-01-31T00:00:00Z", "2029-02-05T00:00:00Z", "grow_alerts.py certs"):
        if present not in certs:
            raise SystemExit(f"cert render missing {present}")
    if "BEGIN CERTIFICATE" in certs or "PRIVATE KEY" in certs or "Deployment" in certs:
        raise SystemExit("cert render included a certificate body or the credential deployment")

    encoded = re.search(r'grow_alerts\.py\.b64: "([^"]+)"', certs)
    if encoded is None:
        raise SystemExit("cert configmap did not inline the script")
    if base64.b64decode(encoded.group(1)) != SCRIPT.read_bytes():
        raise SystemExit("rendered script does not match scripts/grow_alerts.py")

    everything = documents(
        template(
            [
                "alerts.staleShipper.enabled=true",
                "alerts.probeDrift.enabled=true",
                "alerts.vpdOutOfBand.enabled=true",
                "alerts.certExpiry.enabled=true",
            ]
        ).stdout
    )
    if ("PrometheusRule", "grow-probe-drift") not in everything:
        raise SystemExit("all-on render dropped the probe rule")
    if ("CronJob", "grow-shipper-stale") not in everything:
        raise SystemExit("all-on render dropped the shipper job")
    if ("CronJob", "grow-vpd-day") not in everything:
        raise SystemExit("all-on render dropped the vpd job")
    if ("CronJob", "grow-cert-expiry") not in everything:
        raise SystemExit("all-on render dropped the cert job")
    if any(kind == "AlertmanagerConfig" for kind, _name in everything):
        raise SystemExit("email rendered while delivery.email.enabled was false")

    failed = template(["delivery.email.enabled=true"])
    if failed.returncode == 0 or "delivery.email.to is required" not in failed.stderr:
        raise SystemExit("email enable without a recipient should fail the render")

    emailed = assert_render(
        EMAIL_SETS,
        [("AlertmanagerConfig", "grow-alerts-email")],
    )
    if "emailConfigs" not in emailed or "grow-alerts-smtp" not in emailed:
        raise SystemExit("email render did not reference the SMTP secret")
    if "password:" in emailed and "replace-me" in emailed:
        raise SystemExit("email render contained a password")

    print("grow-alert toggles render on and off")


if __name__ == "__main__":
    try:
        check()
    except SystemExit:
        raise
    sys.exit(0)
