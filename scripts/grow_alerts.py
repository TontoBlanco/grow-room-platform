#!/usr/bin/env python3
"""Checks the grow alerts the AC Infinity app cannot see.

The probe-drift alert is a Prometheus rule. These commands are the other
three, plus the credential helper the S3 and Athena jobs use:

  shipper      newest object under readings/dt= for today and yesterday
  vpd-day      one or two Athena partitions, share of samples outside the stage band
  certs        notAfter dates or PEM paths, no certificate contents printed
  credentials  Roles Anywhere credential server for the in-cluster jobs

AWS calls are skipped with --dry-run. boto3 is imported only when a command
actually calls AWS. Run from the repo with the GrowRoom profile, or from the
k3d CronJob. See docs/GROW_ALERTS.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Same inclusive edges as sensor_service.stage. Tests lock the two copies together.
BANDS: dict[str, tuple[float, float]] = {
    "seedling": (0.4, 0.8),
    "veg": (0.8, 1.2),
    "flower": (1.2, 1.5),
    "late_flower": (1.4, 1.6),
}
ALIASES = {
    "clone": "seedling",
    "clones": "seedling",
    "seedling_clone": "seedling",
    "vegetative": "veg",
    "vegetation": "veg",
    "flowering": "flower",
    "lateflower": "late_flower",
}

DEFAULT_BUCKET = "grow-room-telemetry-590183769702"
DEFAULT_PREFIX = "readings/"
DEFAULT_STALE_MINUTES = 30
DEFAULT_OUTSIDE_SHARE = 0.60
DEFAULT_LOOKBACK_DAYS = 1
DEFAULT_WITHIN_DAYS = 30
DEFAULT_CERTS = (
    ("shipper", "2027-01-31T00:00:00Z"),
    ("grafana-reader", "2029-02-05T00:00:00Z"),
)
DEFAULT_WORKGROUP = "grow-room-telemetry"
DEFAULT_DATABASE = "grow_room_telemetry"
DEFAULT_TABLE = "readings"
DEFAULT_REGION = "us-west-2"
PC_SLEEP_SENTENCE = "PC sleep is a known lab limit"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORKGROUP = re.compile(r"^[A-Za-z0-9_-]+$")
_CERT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_ATHENA_PRICE_PER_TB = 5.0
_ATHENA_MIN_BILLED_BYTES = 10_000_000
_MAX_LIST_PAGES = 20
# Credential pod is Python 3.9 (Amazon Linux 2023), which has no datetime.UTC.
_UTC = timezone.utc  # noqa: UP017


def utcnow() -> datetime:
    return datetime.now(_UTC)


def parse_time(text: str) -> datetime:
    """Parse an ISO-8601 timestamp. A trailing Z is UTC. A date is midnight UTC."""
    raw = text.strip()
    if not raw:
        raise ValueError("timestamp is empty")
    if len(raw) == 10:
        raw = raw + "T00:00:00Z"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if "." in raw:
        head, tail = raw.split(".", 1)
        zone = ""
        for sign in ("+", "-"):
            if sign in tail:
                _, offset = tail.split(sign, 1)
                zone = sign + offset
                break
        raw = head + zone
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC)
    return parsed.astimezone(_UTC)


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(_UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_time(moment: datetime, seconds: int) -> datetime:
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), _UTC)


def _normalize_stage(raw: str) -> str:
    text = raw.casefold().replace("-", "_").replace("/", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def band_for_recorded_stage(stage: str | None) -> tuple[float, float]:
    """Band for a stage stored on a reading. Blank and unknown use veg."""
    if stage is None or not str(stage).strip():
        return BANDS["veg"]
    key = _normalize_stage(str(stage))
    name = key if key in BANDS else ALIASES.get(key, "veg")
    return BANDS[name]


def _sql_stage_expr() -> str:
    expr = "lower(trim(coalesce(stage, '')))"
    for old, new in (("-", "_"), ("/", "_"), (" ", "_")):
        expr = f"replace({expr}, '{old}', '{new}')"
    return expr


def _in_list(canonical: str) -> str:
    names = [canonical]
    names.extend(alias for alias, target in ALIASES.items() if target == canonical)
    for name in names:
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError(f"unsafe stage name: {name}")
    quoted = ", ".join(f"'{name}'" for name in sorted(set(names)))
    return f"({quoted})"


def partition_days(today: date, lookback: int) -> list[date]:
    """Yesterday, plus the day before when lookback is 2. Never today, never more."""
    if lookback not in (1, 2):
        raise ValueError("lookback days must be 1 or 2 so the query stays on one or two partitions")
    yesterday = today - timedelta(days=1)
    if lookback == 1:
        return [yesterday]
    return [yesterday - timedelta(days=1), yesterday]


def partition_predicate(days: list[date]) -> str:
    if len(days) == 1:
        return f"dt = '{days[0].isoformat()}'"
    literals = ", ".join(f"'{day.isoformat()}'" for day in days)
    return f"dt IN ({literals})"


def vpd_day_sql(database: str, table: str, days: list[date]) -> str:
    if not _IDENT.fullmatch(database) or not _IDENT.fullmatch(table):
        raise ValueError("database and table must be plain identifiers")
    if not days or len(days) > 2:
        raise ValueError("the VPD query accepts one or two days")
    norm = _sql_stage_expr()
    low = " ".join(
        [
            "CASE",
            f"WHEN {norm} IN {_in_list('seedling')} THEN {BANDS['seedling'][0]}",
            f"WHEN {norm} IN {_in_list('flower')} THEN {BANDS['flower'][0]}",
            f"WHEN {norm} IN {_in_list('late_flower')} THEN {BANDS['late_flower'][0]}",
            f"ELSE {BANDS['veg'][0]}",
            "END",
        ]
    )
    high = " ".join(
        [
            "CASE",
            f"WHEN {norm} IN {_in_list('seedling')} THEN {BANDS['seedling'][1]}",
            f"WHEN {norm} IN {_in_list('flower')} THEN {BANDS['flower'][1]}",
            f"WHEN {norm} IN {_in_list('late_flower')} THEN {BANDS['late_flower'][1]}",
            f"ELSE {BANDS['veg'][1]}",
            "END",
        ]
    )
    where = partition_predicate(days)
    # low_kpa and high_kpa are subquery columns. The outer query must not
    # mention `stage`: Athena would not see that column after the subquery.
    # database, table, and the date literals are validated before this point.
    inner_from = f"FROM {database}.{table} "  # noqa: S608
    inner_where = f"WHERE {where} AND source = 'homeassistant' AND vpd_kpa IS NOT NULL) "  # noqa: S608
    band_columns = f"FROM (SELECT dt, vpd_kpa, {low} AS low_kpa, {high} AS high_kpa "  # noqa: S608
    return (
        "SELECT dt, count(*) AS samples, "
        "count_if(vpd_kpa < low_kpa OR vpd_kpa > high_kpa) AS outside_samples "
        + band_columns
        + inner_from
        + inner_where
        + "AS banded GROUP BY dt ORDER BY dt"
    )


def scan_note(nbytes: int) -> str:
    billed = max(int(nbytes), _ATHENA_MIN_BILLED_BYTES)
    usd = _ATHENA_PRICE_PER_TB * billed / 1_000_000_000_000
    return (
        f"Athena scanned {int(nbytes)} bytes. "
        f"The bill uses a 10 MB minimum, about ${usd:.6f} at $5 per TB. "
        "The workgroup cancels a query that would scan more than 1 GiB."
    )


def shipper_is_stale(newest: datetime | None, now: datetime, minutes: int) -> bool:
    if minutes < 1:
        raise ValueError("minutes must be at least 1")
    if newest is None:
        return True
    return (now - newest) >= timedelta(minutes=minutes)


def shipper_description(
    bucket: str,
    prefix: str,
    minutes: int,
    newest: datetime | None,
    now: datetime,
) -> str:
    root = prefix.strip("/")
    where = f"s3://{bucket}/{root}/"
    if newest is None:
        age = f"no object under today's or yesterday's {root}/dt= partition"
    else:
        minutes_old = int((now - newest).total_seconds() // 60)
        age = f"the newest object is {minutes_old} minutes old ({rfc3339(newest)})"
    return (
        f"No new S3 upload under {where} for {minutes} minutes ({age}). "
        "The shipper may have stopped, or the PC may be asleep. "
        f"{PC_SLEEP_SENTENCE}: this lab runs on a laptop, not an always-on host, "
        "so the alert also fires when the lid was closed. "
        "The AC Infinity app does not see the S3 archive."
    )


def day_prefixes(prefix: str, today: date) -> list[str]:
    root = prefix.strip("/")
    if not root or ".." in root.split("/"):
        raise ValueError(f"unsafe prefix: {prefix}")
    return [f"{root}/dt={(today - timedelta(days=offset)).isoformat()}/" for offset in (0, 1)]


def list_newest(s3, bucket: str, prefix: str, today: date) -> tuple[datetime | None, int]:
    """Newest LastModified under today's and yesterday's dt prefixes only."""
    newest: datetime | None = None
    counted = 0
    for day_prefix in day_prefixes(prefix, today):
        token = None
        for _page in range(_MAX_LIST_PAGES):
            kwargs: dict = {"Bucket": bucket, "Prefix": day_prefix, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            page = s3.list_objects_v2(**kwargs)
            for obj in page.get("Contents") or []:
                counted += 1
                modified = obj["LastModified"]
                if modified.tzinfo is None:
                    modified = modified.replace(tzinfo=_UTC)
                if newest is None or modified > newest:
                    newest = modified
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
            if not token:
                raise RuntimeError(f"truncated list under {day_prefix} had no continuation token")
        else:
            raise RuntimeError(f"too many objects under {day_prefix}; refusing a partial list")
    return newest, counted


class DayShare:
    def __init__(self, day: str, samples: int, outside: int):
        self.day = day
        self.samples = samples
        self.outside = outside

    @property
    def share(self) -> float:
        if self.samples <= 0:
            return 0.0
        return self.outside / self.samples


def days_over_share(rows: list[DayShare], threshold: float, min_samples: int) -> list[DayShare]:
    if not 0.0 < threshold < 1.0:
        raise ValueError("outside share must be between 0 and 1")
    if min_samples < 1:
        raise ValueError("min samples must be at least 1")
    return [row for row in rows if row.samples >= min_samples and row.share > threshold]


def vpd_description(flagged: list[DayShare], threshold: float) -> str:
    parts = [
        (
            f"{row.day}: {row.outside} of {row.samples} samples "
            f"({row.share * 100:.1f}%) were outside the stage band"
        )
        for row in flagged
    ]
    joined = "; ".join(parts)
    return (
        f"VPD was outside the stage band for more than {threshold * 100:.0f}% of the day. "
        f"{joined}. "
        "Each reading uses the band for the stage stored on that row: "
        "seedling 0.4-0.8, veg 0.8-1.2, flower 1.2-1.5, late_flower 1.4-1.6 kPa. "
        "A blank stage uses the veg band. "
        "The AC Infinity app can alarm on the live reading. "
        "It does not score how much of a day sat outside the band."
    )


def cert_is_expiring(not_after: datetime, now: datetime, within_days: int) -> bool:
    if within_days < 1:
        raise ValueError("within days must be at least 1")
    return not_after <= now + timedelta(days=within_days)


def _der_times(der: bytes) -> list[datetime]:
    """First two UTCTime or GeneralizedTime values. Validity is those two."""
    found: list[datetime] = []
    index = 0
    while index < len(der) - 2 and len(found) < 2:
        tag = der[index]
        if tag in (0x17, 0x18):
            length = der[index + 1]
            if length < 128:
                start = index + 2
                raw = der[start : start + length]
                if len(raw) == length:
                    try:
                        found.append(_parse_der_time(raw, tag))
                        index = start + length
                        continue
                    except ValueError:
                        pass
        index += 1
    return found


def _parse_der_time(raw: bytes, tag: int) -> datetime:
    text = raw.decode("ascii")
    if text.endswith("Z"):
        text = text[:-1]
    if tag == 0x17:
        if len(text) < 12:
            raise ValueError("short UTCTime")
        year = int(text[0:2])
        year += 2000 if year < 50 else 1900
        body = text[2:12]
        parsed = datetime.strptime(f"{year}{body}", "%Y%m%d%H%M%S")
    else:
        parsed = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    return parsed.replace(tzinfo=_UTC)


def not_after_from_pem(pem: str) -> datetime:
    """notAfter of the first certificate. Does not print or return the PEM."""
    match = re.search(
        r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
        pem,
        re.DOTALL,
    )
    if match is None:
        raise ValueError("no certificate in pem")
    body = re.sub(r"\s+", "", match.group(1))
    try:
        der = base64.b64decode(body, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("certificate pem is not valid base64") from exc
    times = _der_times(der)
    if len(times) < 2:
        raise ValueError("certificate did not contain a validity window")
    not_before, not_after = times[0], times[1]
    if not_after <= not_before:
        not_before, not_after = not_after, not_before
    return not_after


def not_after_from_path(path: str) -> datetime:
    with open(path, encoding="utf-8") as handle:
        pem = handle.read()
    return not_after_from_pem(pem)


def cert_description(name: str, not_after: datetime, within_days: int, source: str) -> str:
    return (
        f"Certificate {name} expires {rfc3339(not_after)} ({source}), "
        f"which is within {within_days} days. "
        "The AC Infinity app does not know about the Roles Anywhere leaf "
        "or the Grafana reader certificate. "
        "Renew the leaf under C:\\src\\grow-room-pki and do not commit the new file."
    )


def build_alert(
    *,
    name: str,
    summary: str,
    description: str,
    namespace: str,
    starts_at: datetime,
    ends_at: datetime,
    extra: dict[str, str] | None = None,
) -> dict:
    labels = {
        "alertname": name,
        "severity": "warning",
        "grow_alert": "true",
        "room": "grow-room",
        "namespace": namespace,
    }
    if extra:
        labels.update(extra)
    if starts_at >= ends_at:
        starts_at = ends_at - timedelta(minutes=1)
    return {
        "labels": labels,
        "annotations": {"summary": summary, "description": description},
        "startsAt": rfc3339(starts_at),
        "endsAt": rfc3339(ends_at),
    }


def firing_ends(now: datetime, seconds: int) -> datetime:
    return now + timedelta(seconds=seconds)


def resolved_ends(now: datetime) -> tuple[datetime, datetime]:
    ends = now - timedelta(seconds=1)
    return ends - timedelta(minutes=1), ends


def post_alerts(url: str, alerts: list[dict], opener=None) -> None:
    if not alerts:
        print("no alertmanager updates", flush=True)
        return
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"alertmanager url must be http or https: {url}")
    payload = json.dumps(alerts).encode("utf-8")
    # Scheme is checked above. S310 flags Request as well as urlopen.
    request = urllib.request.Request(  # noqa: S310
        url.rstrip("/") + "/api/v2/alerts",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=10) as response:  # noqa: S310
        status = getattr(response, "status", 200)
        if status >= 300:
            raise RuntimeError(f"alertmanager returned {status}")
    print(f"posted {len(alerts)} alert update(s)", flush=True)


def emit(alerts: list[dict], *, dry_run: bool, url: str) -> int:
    print(json.dumps(alerts, indent=2), flush=True)
    if dry_run:
        print("dry-run: not posted", flush=True)
        return 0
    if not url:
        raise ValueError("alertmanager url is required (or pass --dry-run)")
    post_alerts(url, alerts)
    return 0


def _client(service: str, region: str):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed; pip install boto3") from exc
    return boto3.client(service, region_name=region)


def parse_athena_table(result: dict) -> list[dict[str, str]]:
    rows = result.get("ResultSet", {}).get("Rows", [])
    if len(rows) < 2:
        return []
    header = [cell.get("VarCharValue", "") for cell in rows[0].get("Data", [])]
    parsed = []
    for row in rows[1:]:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        if len(values) != len(header):
            raise ValueError("athena row does not match the header")
        parsed.append(dict(zip(header, values, strict=True)))
    return parsed


def wait_athena(client, query_id: str, sleep, attempts: int = 30) -> dict:
    last = {}
    for _ in range(attempts):
        last = client.get_query_execution(QueryExecutionId=query_id)
        state = last["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return last
        if state in {"FAILED", "CANCELLED"}:
            reason = last["QueryExecution"]["Status"].get("StateChangeReason", state)
            raise RuntimeError(f"athena query {state}: {reason}")
        sleep(2)
    raise TimeoutError(f"athena query {query_id} did not finish")


def run_vpd_query(
    client,
    sql: str,
    *,
    database: str,
    workgroup: str,
    sleep,
) -> tuple[list[DayShare], int]:
    if not _WORKGROUP.fullmatch(workgroup):
        raise ValueError("unsafe workgroup name")
    started = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )
    query_id = started["QueryExecutionId"]
    finished = wait_athena(client, query_id, sleep)
    stats = finished["QueryExecution"].get("Statistics", {})
    scanned = int(stats.get("DataScannedInBytes") or 0)
    table = parse_athena_table(client.get_query_results(QueryExecutionId=query_id))
    shares = []
    for row in table:
        shares.append(
            DayShare(
                day=str(row.get("dt") or ""),
                samples=int(row.get("samples") or 0),
                outside=int(row.get("outside_samples") or 0),
            )
        )
    return shares, scanned


def container_document(payload: dict) -> dict:
    required = ("AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError("credential-process response missing " + ",".join(missing))
    parse_time(payload["Expiration"])
    # AccessKeyId is the botocore container shape. AccessKeyID is the ECS shape
    # the Grafana plugin also accepts. Both point at the same temporary key.
    return {
        "AccessKeyId": payload["AccessKeyId"],
        "AccessKeyID": payload["AccessKeyId"],
        "SecretAccessKey": payload["SecretAccessKey"],
        "Token": payload["SessionToken"],
        "Expiration": payload["Expiration"],
    }


def fetch_process_credentials(helper: str, identity_dir: str, region: str, run=None) -> dict:
    if not os.path.isabs(helper):
        raise ValueError("signing helper path must be absolute")
    runner = run or subprocess.run

    def read_arn(name: str) -> str:
        path = os.path.join(identity_dir, name)
        with open(path, encoding="utf-8") as handle:
            return "".join(handle.read().split())

    command = [
        helper,
        "credential-process",
        "--certificate",
        os.path.join(identity_dir, "tls.crt"),
        "--private-key",
        os.path.join(identity_dir, "tls.key"),
        "--trust-anchor-arn",
        read_arn("trust-anchor-arn"),
        "--profile-arn",
        read_arn("profile-arn"),
        "--role-arn",
        read_arn("role-arn"),
        "--region",
        region,
    ]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        lines = (completed.stderr or "credential-process failed").strip().splitlines()
        detail = lines[-1][:300] if lines else "credential-process failed"
        raise RuntimeError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("credential-process did not return JSON") from exc
    return container_document(payload)


class _CredentialCache:
    def __init__(self, fetch):
        self._fetch = fetch
        self._lock = threading.Lock()
        self._body = None
        self._refresh_by = None

    def get(self) -> dict:
        with self._lock:
            now = utcnow()
            if self._body is not None and self._refresh_by is not None and now < self._refresh_by:
                return self._body
            body = self._fetch()
            self._body = body
            self._refresh_by = parse_time(body["Expiration"]) - timedelta(minutes=5)
            return body


def serve_credentials(fetch, port: int) -> None:
    cache = _CredentialCache(fetch)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = self.path.split("?", 1)[0]
            if path not in {"/healthz", "/credentials"}:
                self._json(404, {"code": "NotFound", "message": "not found"})
                return
            try:
                body = cache.get()
            except Exception as exc:
                status = 503 if path == "/healthz" else 500
                self._json(status, {"code": "CredentialProcessFailed", "message": str(exc)[:300]})
                return
            if path == "/healthz":
                self._json(200, {"status": "ok"})
                return
            self._json(200, body)

        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("grow-alerts-credentials " + (fmt % args) + "\n")

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - pod Service target
    host, bound = server.server_address
    print(f"container credentials listening on http://{host}:{bound}/credentials", flush=True)
    server.serve_forever()


def _parse_now(text: str) -> datetime:
    if not text:
        return utcnow()
    return parse_time(text)


def _cert_pairs(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    paths = {}
    for item in args.cert_path:
        name, _, path = item.partition("=")
        if not path or not _CERT_NAME.fullmatch(name):
            raise ValueError(f"use --cert-path name=/path, got {item!r}")
        paths[name] = path
    chosen = args.cert or [f"{name}={expiry}" for name, expiry in DEFAULT_CERTS]
    pairs = []
    for item in chosen:
        name, _, expiry = item.partition("=")
        if not expiry or not _CERT_NAME.fullmatch(name):
            raise ValueError(f"use --cert name=YYYY-MM-DDTHH:MM:SSZ, got {item!r}")
        pairs.append((name, expiry, paths.get(name, "")))
    return pairs


def command_shipper(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    if args.newest:
        newest = parse_time(args.newest)
        counted = 0
    elif args.dry_run:
        for day_prefix in day_prefixes(args.prefix, now.date()):
            print(f"would list s3://{args.bucket}/{day_prefix}", flush=True)
        print("dry-run: not listed", flush=True)
        return 0
    else:
        newest, counted = list_newest(
            _client("s3", args.region),
            args.bucket,
            args.prefix,
            now.date(),
        )
        print(f"listed {counted} object(s) under 2 day prefixes", flush=True)
        print(
            "S3 LIST is about $0.005 per 1000 requests. This check is 2 requests "
            "unless a day prefix is longer than 1000 keys.",
            flush=True,
        )
    stale = shipper_is_stale(newest, now, args.minutes)
    description = shipper_description(args.bucket, args.prefix, args.minutes, newest, now)
    if stale:
        if newest is None:
            starts = now - timedelta(minutes=args.minutes)
        else:
            starts = newest + timedelta(minutes=args.minutes)
        starts_at, ends_at = starts, firing_ends(now, 20 * 60)
        summary = f"No new S3 upload under {args.prefix} for {args.minutes} minutes"
    else:
        starts_at, ends_at = resolved_ends(now)
        summary = "S3 uploads under readings/ are current"
        description = (
            f"The newest object under s3://{args.bucket}/{args.prefix.strip('/')}/ "
            f"is newer than {args.minutes} minutes ({rfc3339(newest)})."
        )
    alert = build_alert(
        name="GrowShipperStale",
        summary=summary,
        description=description,
        namespace=args.namespace,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    print(("firing" if stale else "clear") + " GrowShipperStale", flush=True)
    return emit([alert], dry_run=args.dry_run, url=args.alertmanager_url)


def command_vpd(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    days = partition_days(now.date(), args.lookback_days)
    sql = vpd_day_sql(args.database, args.table, days)
    print(sql, flush=True)
    if args.dry_run:
        print("dry-run: query not executed", flush=True)
        return 0
    shares, scanned = run_vpd_query(
        _client("athena", args.region),
        sql,
        database=args.database,
        workgroup=args.workgroup,
        sleep=args.sleep,
    )
    print(scan_note(scanned), flush=True)
    flagged = days_over_share(shares, args.outside_share, args.min_samples)
    if flagged:
        alert = build_alert(
            name="GrowVpdOutOfBand",
            summary="VPD was outside the stage band for most of a day",
            description=vpd_description(flagged, args.outside_share),
            namespace=args.namespace,
            starts_at=datetime(days[0].year, days[0].month, days[0].day, tzinfo=_UTC),
            ends_at=firing_ends(now, 36 * 60 * 60),
        )
        print("firing GrowVpdOutOfBand", flush=True)
        return emit([alert], dry_run=False, url=args.alertmanager_url)
    starts_at, ends_at = resolved_ends(now)
    alert = build_alert(
        name="GrowVpdOutOfBand",
        summary="VPD stayed inside the stage band often enough",
        description="The queried day or days were within the configured outside-share.",
        namespace=args.namespace,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    print("clear GrowVpdOutOfBand", flush=True)
    return emit([alert], dry_run=False, url=args.alertmanager_url)


def command_certs(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    alerts = []
    for name, expiry, path in _cert_pairs(args):
        if path:
            not_after = not_after_from_path(path)
            source = "read from the configured path"
        else:
            not_after = parse_time(expiry)
            source = "configured notAfter"
        expiring = cert_is_expiring(not_after, now, args.within_days)
        if expiring:
            starts = not_after - timedelta(days=args.within_days)
            ends = firing_ends(now, 36 * 60 * 60)
            summary = f"{name} certificate expires within {args.within_days} days"
            description = cert_description(name, not_after, args.within_days, source)
            print(f"firing GrowCertExpiring {name}", flush=True)
        else:
            starts, ends = resolved_ends(now)
            summary = f"{name} certificate is outside the expiry window"
            description = (
                f"Certificate {name} expires {rfc3339(not_after)}, "
                f"more than {args.within_days} days from now."
            )
            print(f"clear GrowCertExpiring {name}", flush=True)
        alerts.append(
            build_alert(
                name="GrowCertExpiring",
                summary=summary,
                description=description,
                namespace=args.namespace,
                starts_at=starts,
                ends_at=ends,
                extra={"cert": name},
            )
        )
    return emit(alerts, dry_run=args.dry_run, url=args.alertmanager_url)


def command_credentials(args: argparse.Namespace) -> int:
    identity = args.identity_dir
    cert = os.path.join(identity, "tls.crt")
    key = os.path.join(identity, "tls.key")
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        print(
            "grafana reader identity is not mounted; "
            "create secret grafana-athena-identity before enabling this job",
            flush=True,
        )
        return 1

    def fetch() -> dict:
        return fetch_process_credentials(args.helper, identity, args.region)

    serve_credentials(fetch, args.port)
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--alertmanager-url", default=os.environ.get("ALERTMANAGER_URL", ""))
    parser.add_argument(
        "--namespace",
        default=os.environ.get("GROW_ALERTS_NAMESPACE", "monitoring"),
    )
    parser.add_argument("--now", default="", help="Override the clock (ISO-8601, UTC)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grow alerts the AC Infinity app cannot see.")
    sub = parser.add_subparsers(dest="command", required=True)

    shipper = sub.add_parser("shipper", help="List readings/ for today and yesterday")
    _add_common(shipper)
    shipper.add_argument("--bucket", default=DEFAULT_BUCKET)
    shipper.add_argument("--prefix", default=DEFAULT_PREFIX)
    shipper.add_argument("--minutes", type=int, default=DEFAULT_STALE_MINUTES)
    shipper.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    shipper.add_argument("--newest", default="", help="Skip S3 and evaluate this timestamp")
    shipper.set_defaults(func=command_shipper)

    vpd = sub.add_parser("vpd-day", help="Athena share of a day outside the stage band")
    _add_common(vpd)
    vpd.add_argument("--workgroup", default=DEFAULT_WORKGROUP)
    vpd.add_argument("--database", default=DEFAULT_DATABASE)
    vpd.add_argument("--table", default=DEFAULT_TABLE)
    vpd.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    vpd.add_argument("--outside-share", type=float, default=DEFAULT_OUTSIDE_SHARE)
    vpd.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    vpd.add_argument("--min-samples", type=int, default=1)
    vpd.set_defaults(func=command_vpd, sleep=lambda _seconds: None)

    certs = sub.add_parser("certs", help="Compare configured expiry dates or PEM paths")
    _add_common(certs)
    certs.add_argument("--cert", action="append", default=[], help="name=notAfter (repeatable)")
    certs.add_argument("--cert-path", action="append", default=[], help="name=/path/to/cert.pem")
    certs.add_argument("--within-days", type=int, default=DEFAULT_WITHIN_DAYS)
    certs.set_defaults(func=command_certs)

    creds = sub.add_parser("credentials", help="Serve Roles Anywhere credentials")
    creds.add_argument(
        "--identity-dir",
        default=os.environ.get("GROW_ALERTS_IDENTITY_DIR", "/etc/grow-alerts/identity"),
    )
    creds.add_argument(
        "--helper",
        default=os.environ.get("AWS_SIGNING_HELPER", "/opt/rolesanywhere/aws_signing_helper"),
    )
    creds.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    creds.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GROW_ALERTS_CREDENTIAL_PORT", "9911")),
    )
    creds.set_defaults(func=command_credentials)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
