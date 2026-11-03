"""Decision logic for the grow alerts the controller app cannot see."""

import base64
import importlib.util
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sensor_service import stage

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("grow_alerts", ROOT / "scripts" / "grow_alerts.py")
grow = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(grow)

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)


def test_chart_copy_matches_the_script():
    script = (ROOT / "scripts" / "grow_alerts.py").read_bytes()
    chart = (ROOT / "charts" / "grow-alerts" / "files" / "grow_alerts.py").read_bytes()
    assert script == chart
    assert not script.startswith(b"\xef\xbb\xbf")


def test_bands_and_aliases_match_stage_py():
    assert grow.BANDS == stage._DEFAULT_BANDS
    assert grow.ALIASES == stage._ALIASES


@pytest.mark.parametrize(
    "raw",
    [None, "", "  ", "veg", "clone", "Late Flower", "flowering", "nope", "seedling/clone"],
)
def test_recorded_stage_uses_the_stage_module_band(raw):
    if raw is None or not str(raw).strip():
        expected = stage._DEFAULT_BANDS["veg"]
    else:
        key = stage._normalize(str(raw))
        name = key if key in stage._DEFAULT_BANDS else stage._ALIASES.get(key, "veg")
        expected = stage._DEFAULT_BANDS[name]
    assert grow.band_for_recorded_stage(raw) == expected


def test_vpd_sql_is_one_partition_and_names_the_bands():
    days = grow.partition_days(NOW.date(), 1)
    sql = grow.vpd_day_sql("grow_room_telemetry", "readings", days)
    assert "dt = '2026-11-02'" in sql
    assert "2026-11-03" not in sql
    assert "current_date" not in sql.lower()
    assert "interval" not in sql.lower()
    assert "source = 'homeassistant'" in sql
    for low, high in grow.BANDS.values():
        assert str(low) in sql
        assert str(high) in sql
    assert "clone" in sql
    assert "lateflower" in sql


def test_vpd_sql_two_day_lookback_and_rejects_a_wider_scan():
    days = grow.partition_days(NOW.date(), 2)
    sql = grow.vpd_day_sql("grow_room_telemetry", "readings", days)
    assert "dt IN ('2026-11-01', '2026-11-02')" in sql
    with pytest.raises(ValueError):
        grow.partition_days(NOW.date(), 3)
    with pytest.raises(ValueError):
        grow.vpd_day_sql("grow_room_telemetry", "readings;drop", days)


def test_outside_share_is_strict():
    even = grow.DayShare("2026-11-02", 10, 6)
    over = grow.DayShare("2026-11-02", 10, 7)
    assert grow.days_over_share([even], 0.60, 1) == []
    flagged = grow.days_over_share([over], 0.60, 1)
    assert flagged == [over]
    assert "AC Infinity" in grow.vpd_description(flagged, 0.60)


def test_empty_day_is_not_an_out_of_band_alert():
    assert grow.days_over_share([grow.DayShare("2026-11-02", 0, 0)], 0.60, 1) == []


def test_shipper_stale_boundary_and_text():
    newest = NOW - timedelta(minutes=30)
    assert grow.shipper_is_stale(newest, NOW, 30) is True
    assert grow.shipper_is_stale(newest + timedelta(seconds=1), NOW, 30) is False
    assert grow.shipper_is_stale(None, NOW, 30) is True
    text = grow.shipper_description(grow.DEFAULT_BUCKET, "readings/", 30, None, NOW)
    assert grow.PC_SLEEP_SENTENCE in text
    assert "s3://grow-room-telemetry-590183769702/readings/" in text
    assert "AC Infinity" in text


def test_list_newest_stays_on_two_day_prefixes():
    class FakeS3:
        def __init__(self):
            self.calls = []

        def list_objects_v2(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["Prefix"].endswith("2026-11-03/"):
                return {
                    "Contents": [{"LastModified": datetime(2026, 11, 3, 12, 0, tzinfo=UTC)}],
                    "IsTruncated": False,
                }
            return {"IsTruncated": False}

    fake = FakeS3()
    newest, counted = grow.list_newest(fake, grow.DEFAULT_BUCKET, "readings/", NOW.date())
    assert counted == 1
    assert newest == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    prefixes = [call["Prefix"] for call in fake.calls]
    assert prefixes == ["readings/dt=2026-11-03/", "readings/dt=2026-11-02/"]
    assert all(call["Bucket"] == grow.DEFAULT_BUCKET for call in fake.calls)
    assert all(call["MaxKeys"] == 1000 for call in fake.calls)


def test_cert_window_includes_the_30th_day_and_already_expired():
    expiry = datetime(2027, 1, 31, tzinfo=UTC)
    assert grow.cert_is_expiring(expiry, datetime(2027, 1, 1, tzinfo=UTC), 30) is True
    assert grow.cert_is_expiring(expiry, datetime(2026, 12, 31, tzinfo=UTC), 30) is False
    assert grow.cert_is_expiring(expiry, datetime(2027, 2, 1, tzinfo=UTC), 30) is True


def test_pem_not_after_is_the_second_time_and_not_echoed():
    def utc(text: str) -> bytes:
        raw = text.encode("ascii")
        return bytes([0x17, len(raw)]) + raw

    der = b"\x30\x20" + utc("260101000000Z") + utc("270131120000Z")
    pem = (
        "-----BEGIN CERTIFICATE-----\n"
        + base64.encodebytes(der).decode()
        + "-----END CERTIFICATE-----\n"
    )
    found = grow.not_after_from_pem(pem)
    assert found == datetime(2027, 1, 31, 12, 0, tzinfo=UTC)
    description = grow.cert_description("shipper", found, 30, "configured notAfter")
    assert "BEGIN CERTIFICATE" not in description
    assert "shipper" in description


@pytest.mark.skipif(
    shutil.which("openssl") is None, reason="openssl is required to mint a fixture cert"
)
def test_pem_parser_matches_openssl(tmp_path):
    cert = tmp_path / "leaf.pem"
    key = tmp_path / "leaf.key"
    import subprocess

    openssl = shutil.which("openssl")
    assert openssl is not None
    subprocess.run(  # noqa: S603
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "40",
            "-nodes",
            "-subj",
            "/CN=grow-alerts-test",
        ],
        check=True,
        capture_output=True,
    )
    parsed = grow.not_after_from_path(str(cert))
    printed = subprocess.run(  # noqa: S603
        [openssl, "x509", "-enddate", "-noout", "-in", str(cert)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # notAfter=Nov 13 12:00:00 2026 GMT
    stamp = printed.split("=", 1)[1]
    expected = datetime.strptime(stamp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    assert parsed == expected
    assert key.read_text(encoding="utf-8") not in cert.read_text(encoding="utf-8")


def test_athena_result_and_scan_note():
    class FakeAthena:
        def __init__(self):
            self.sql = None
            self.polls = 0

        def start_query_execution(self, **kwargs):
            self.sql = kwargs["QueryString"]
            assert kwargs["WorkGroup"] == "grow-room-telemetry"
            return {"QueryExecutionId": "q1"}

        def get_query_execution(self, **kwargs):
            self.polls += 1
            state = "RUNNING" if self.polls == 1 else "SUCCEEDED"
            return {
                "QueryExecution": {
                    "Status": {"State": state},
                    "Statistics": {"DataScannedInBytes": 200000},
                }
            }

        def get_query_results(self, **kwargs):
            return {
                "ResultSet": {
                    "Rows": [
                        {
                            "Data": [
                                {"VarCharValue": "dt"},
                                {"VarCharValue": "samples"},
                                {"VarCharValue": "outside_samples"},
                            ]
                        },
                        {
                            "Data": [
                                {"VarCharValue": "2026-11-02"},
                                {"VarCharValue": "100"},
                                {"VarCharValue": "70"},
                            ]
                        },
                    ]
                }
            }

    sleeps = []
    fake = FakeAthena()
    shares, scanned = grow.run_vpd_query(
        fake,
        "select 1",
        database="grow_room_telemetry",
        workgroup="grow-room-telemetry",
        sleep=sleeps.append,
    )
    assert sleeps == [2]
    assert scanned == 200000
    assert shares[0].share == 0.7
    note = grow.scan_note(scanned)
    assert "200000" in note
    assert "10 MB" in note
    assert "$" in note


def test_failed_athena_query_does_not_look_like_a_clear_day():
    class Failed:
        def start_query_execution(self, **kwargs):
            return {"QueryExecutionId": "q1"}

        def get_query_execution(self, **kwargs):
            return {
                "QueryExecution": {
                    "Status": {"State": "FAILED", "StateChangeReason": "boom"},
                    "Statistics": {},
                }
            }

    with pytest.raises(RuntimeError, match="boom"):
        grow.run_vpd_query(
            Failed(),
            "select 1",
            database="grow_room_telemetry",
            workgroup="grow-room-telemetry",
            sleep=lambda _seconds: None,
        )


def test_cli_dry_runs_do_not_post(capsys):
    assert (
        grow.main(["vpd-day", "--dry-run", "--now", "2026-11-03T18:00:00Z", "--lookback-days", "1"])
        == 0
    )
    vpd_out = capsys.readouterr().out
    assert "dt = '2026-11-02'" in vpd_out
    assert "query not executed" in vpd_out

    assert (
        grow.main(
            [
                "shipper",
                "--dry-run",
                "--now",
                "2026-11-03T18:00:00Z",
                "--newest",
                "2026-11-03T16:00:00Z",
            ]
        )
        == 0
    )
    ship_out = capsys.readouterr().out
    assert "firing GrowShipperStale" in ship_out
    assert grow.PC_SLEEP_SENTENCE in ship_out
    assert "dry-run: not posted" in ship_out

    assert (
        grow.main(
            [
                "certs",
                "--dry-run",
                "--now",
                "2027-01-15T00:00:00Z",
                "--cert",
                "shipper=2027-01-31T00:00:00Z",
            ]
        )
        == 0
    )
    cert_out = capsys.readouterr().out
    assert "firing GrowCertExpiring shipper" in cert_out
    assert "BEGIN CERTIFICATE" not in cert_out


def test_cli_rejects_a_three_day_athena_lookback():
    assert grow.main(["vpd-day", "--dry-run", "--lookback-days", "3"]) == 1


def test_post_alerts_rejects_non_http_and_posts_json():
    with pytest.raises(ValueError):
        grow.post_alerts("file:///tmp/alerts", [{"labels": {}}])

    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return Response()

    grow.post_alerts(
        "http://alertmanager.monitoring.svc:9093",
        [{"labels": {"alertname": "GrowCertExpiring"}}],
        opener,
    )
    assert seen["url"].endswith("/api/v2/alerts")
    assert seen["body"][0]["labels"]["alertname"] == "GrowCertExpiring"
    assert seen["timeout"] == 10


def test_credential_error_does_not_include_the_session_token(tmp_path):
    secret = "SESSION-TOKEN-SHOULD-NOT-LEAK"
    for name in ("trust-anchor-arn", "profile-arn", "role-arn"):
        (tmp_path / name).write_text("arn:aws:iam::123456789012:role/example\n", encoding="utf-8")

    def runner(command, capture_output, text, check):
        class Completed:
            returncode = 1
            stdout = secret
            stderr = "certificate expired"

        return Completed()

    with pytest.raises(RuntimeError, match="certificate expired") as exc:
        grow.fetch_process_credentials(
            "/usr/bin/aws_signing_helper",
            str(tmp_path),
            "us-west-2",
            run=runner,
        )
    assert secret not in str(exc.value)


def test_container_document_has_both_key_shapes():
    body = grow.container_document(
        {
            "AccessKeyId": "AKI",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": "2026-11-03T20:00:00Z",
        }
    )
    assert body["AccessKeyId"] == "AKI"
    assert body["AccessKeyID"] == "AKI"
    assert body["Token"] == "token"


def test_default_cert_dates_match_the_chart_values():
    values = (ROOT / "charts" / "grow-alerts" / "values.yaml").read_text(encoding="utf-8")
    for name, expiry in grow.DEFAULT_CERTS:
        assert f"name: {name}" in values
        assert expiry in values
    assert "enabled: false" in values
    assert grow.DEFAULT_BUCKET in values
