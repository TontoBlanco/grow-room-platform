# scripts/ship_readings.py
"""Ship tent readings from a running sensor-service to S3 as JSON Lines.

One object per batch at  <prefix>/dt=YYYY-MM-DD/HHMMSS-<id>.json  (UTC date).
Home PC:  python scripts/ship_readings.py --bucket grow-room-telemetry-590183769702
EKS job:  python ship_readings.py --once --prefix raw --url http://sensor-service.grow-room.svc:8000/readings
"""

from __future__ import annotations

import argparse
import json
import socket
import time
import urllib.request
import uuid
from datetime import UTC, datetime


def flatten(r: dict) -> dict:
    """Keep the fields the Glue table knows about; nested dicts become prefixed columns.

    ``stage`` is optional. It is added only when ``/readings`` sent a growth
    stage, so a replay of an older payload keeps the previous keys. Athena
    returns null for objects that omit it.
    """
    probe = r.get("probe") or {}
    controller = r.get("controller") or {}
    row = {
        "timestamp": r.get("timestamp"),
        "temperature_c": r.get("temperature_c"),
        "humidity_percent": r.get("humidity_percent"),
        "vpd_kpa": r.get("vpd_kpa"),
        "controller_vpd_kpa": controller.get("vpd_kpa"),
        "probe_temperature_c": probe.get("temperature_c"),
        "probe_humidity_percent": probe.get("humidity_percent"),
        "co2_ppm": r.get("co2_ppm"),
        "source": r.get("source"),
        "host": socket.gethostname(),
    }
    stage = r.get("growth_stage")
    if isinstance(stage, str) and stage.strip():
        row["stage"] = stage.strip()
    return row


def fetch(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"only http(s) URLs allowed: {url}")
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - scheme checked above
        return json.load(resp)


def upload(s3, bucket: str, prefix: str, rows: list[dict]) -> str:
    now = datetime.now(UTC)
    key = f"{prefix}/dt={now:%Y-%m-%d}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}.json"
    body = "\n".join(json.dumps(row) for row in rows) + "\n"
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode(), ContentType="application/x-ndjson")
    return key


def main() -> None:
    import boto3

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000/readings")
    p.add_argument("--bucket", required=True)
    p.add_argument("--prefix", default="readings")
    p.add_argument("--interval", type=int, default=60, help="seconds between reads")
    p.add_argument("--batch", type=int, default=10, help="readings per S3 object")
    p.add_argument("--once", action="store_true", help="read once, upload, exit")
    p.add_argument("--dry-run", action="store_true", help="print instead of upload")
    a = p.parse_args()

    s3 = None if a.dry_run else boto3.client("s3")
    buf: list[dict] = []
    while True:
        try:
            buf.append(flatten(fetch(a.url)))
        except Exception as exc:  # keep running through HA blips
            print(f"read failed: {exc}", flush=True)
        if buf and (a.once or len(buf) >= a.batch):
            if a.dry_run:
                print(json.dumps(buf, indent=2), flush=True)
                buf = []
            else:
                try:
                    key = upload(s3, a.bucket, a.prefix, buf)
                    print(f"wrote {key} ({len(buf)} rows)", flush=True)
                    buf = []
                except Exception as exc:  # keep the buffer, retry next cycle
                    print(f"upload failed, will retry: {exc}", flush=True)
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
