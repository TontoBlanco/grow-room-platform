"""The Grafana reader is a separate role. The shipper stays write-only."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEMETRY = ROOT / "infra" / "telemetry"
MAIN = (TELEMETRY / "main.tf").read_text()
READER = (TELEMETRY / "grafana_reader.tf").read_text()
VALUES = (ROOT / "monitoring" / "values-k3d.yaml").read_text()
DOC = (ROOT / "docs" / "ATHENA_GRAFANA.md").read_text()


def _hcl_block(text: str, header: str) -> str:
    """Return the HCL block that starts at header, skipping ${...} braces."""
    start = text.index(header)
    i = text.index("{", start)
    depth = 0
    j = i
    while j < len(text):
        if text.startswith("${", j):
            j += 2
            interp = 1
            while j < len(text) and interp:
                if text.startswith("${", j):
                    interp += 1
                    j += 2
                    continue
                if text[j] == "}":
                    interp -= 1
                j += 1
            continue
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
        j += 1
    raise AssertionError(f"unbalanced block {header}")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _statement(policy: str, sid: str) -> str:
    idx = policy.index(f'"{sid}"')
    start = policy.rfind("statement", 0, idx)
    return _hcl_block(policy[start:], "statement")


def test_shipper_policy_stays_write_only():
    policy = _hcl_block(MAIN, 'data "aws_iam_policy_document" "shipper"')
    flat = _flat(policy)
    assert 'actions = ["s3:PutObject"]' in flat
    assert "/readings/*" in policy
    assert 'actions = ["kms:GenerateDataKey", "kms:Decrypt"]' in flat
    for forbidden in (
        "s3:GetObject",
        "s3:ListBucket",
        "s3:DeleteObject",
        "athena:",
        "glue:",
        "s3:PutObjectAcl",
    ):
        assert forbidden not in policy
    trust = _flat(_hcl_block(MAIN, 'data "aws_iam_policy_document" "shipper_trust"'))
    assert 'values = ["grow-room-home-shipper"]' in trust
    profile = _flat(_hcl_block(MAIN, 'resource "aws_rolesanywhere_profile" "home"'))
    assert "role_arns = [aws_iam_role.shipper.arn]" in profile
    assert "grafana_reader" not in profile


def test_grafana_reader_is_least_privilege_and_separate():
    assert "grow-room-grafana-reader" in READER
    profile = _flat(_hcl_block(READER, 'resource "aws_rolesanywhere_profile" "grafana"'))
    assert 'name = "grow-room-grafana"' in profile
    assert "role_arns = [aws_iam_role.grafana_reader.arn]" in profile
    assert "shipper" not in profile
    policy = _hcl_block(READER, 'data "aws_iam_policy_document" "grafana_reader"')
    assert "aws_athena_workgroup.telemetry.arn" in policy
    assert "athena:StartQueryExecution" in policy
    assert "glue:GetTable" in policy
    assert "kms:Decrypt" in policy
    assert "kms:GenerateDataKey" in policy
    assert "${aws_s3_bucket.telemetry.arn}/readings/*" in policy
    assert "${aws_s3_bucket.telemetry.arn}/athena-results/*" in policy
    deny = _statement(policy, "DenyWriteReadings")
    assert 'effect = "Deny"' in _flat(deny)
    assert "s3:PutObject" in deny
    assert "/readings/*" in deny
    write = _statement(policy, "WriteQueryResults")
    assert "/athena-results/*" in write
    assert "readings" not in write
    assert 'name          = "stage"' in MAIN or 'name = "stage"' in _flat(MAIN)


def test_grafana_values_pin_the_helper_and_do_not_carry_secrets():
    assert "grafana-athena-datasource@3.4.2" in VALUES
    assert "http://127.0.0.1:9911/credentials" in VALUES
    assert "AWS_CONTAINER_CREDENTIALS_FULL_URI: http://127.0.0.1:9911/credentials" in VALUES
    assert "forward_settings_to_plugins: grafana-athena-datasource" in VALUES
    assert "authType: default" in VALUES
    assert "allowed_auth_providers: default" in VALUES
    assert "credential-process" in VALUES
    assert "forward_host_env_vars" not in VALUES
    assert "AWS_EC2_METADATA_SERVICE_ENDPOINT" not in VALUES
    assert "secretName: grafana-athena-identity" in VALUES
    assert "optional: true" in VALUES
    assert "beec9ed1c492d93db809890f16713e3556353294b823c2184ad4e891f1b2b54d" in VALUES
    assert "3d131aa888cd56da446f9c6bb460b1f0569f6c7edc74eae6193a2fe3928883ba" in VALUES
    assert "releases/1.8.5/" in VALUES
    assert "AKIA" not in VALUES
    assert "BEGIN PRIVATE KEY" not in VALUES
    assert "BEGIN CERTIFICATE" not in VALUES


def test_runbook_uses_the_real_names():
    for needle in (
        "grafana-athena-identity",
        "grow-room-grafana-reader",
        "athena-grow-room",
        "grafana-athena-datasource@3.4.2",
        "http://127.0.0.1:9911/credentials",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "forward_settings_to_plugins",
        "grafana-reader.pem",
        "separate drive",
        "Grafana reads `grafana.ini` at process start",
        "Argo only updates the ConfigMap",
        "kubectl -n monitoring rollout restart deploy/monitoring-grafana",
        "kubectl -n argocd patch application monitoring --type merge --patch-file",
        "terraform -chdir=infra/telemetry",
        "helm upgrade --install monitoring",
        "C:\\src\\grow-room-pki\\ca.pem",
        "/mnt/c/src/grow-room-pki/ca.pem",
        "aws sts get-caller-identity --query Account --output text",
    ):
        assert needle in DOC
    for placeholder in ("<ACCOUNT", "YOUR_", "TODO", "changeme", "example.com"):
        assert placeholder not in DOC


def _credential_server_source() -> str:
    lines = VALUES.splitlines()
    opener = "exec python3 - << 'ATHENA_CONTAINER_CREDENTIALS_PY'"
    start = next(i for i, line in enumerate(lines) if line.strip() == opener)
    end = next(
        i
        for i, line in enumerate(lines)
        if i > start and line.strip() == "ATHENA_CONTAINER_CREDENTIALS_PY"
    )
    body = lines[start + 1 : end]
    indent = len(body[0]) - len(body[0].lstrip(" "))
    stripped = []
    for line in body:
        if line.strip() == "":
            stripped.append("")
            continue
        assert line.startswith(" " * indent)
        stripped.append(line[indent:])
    return "\n".join(stripped) + "\n"


def _load_credential_server(tmp_path: Path):
    path = tmp_path / "athena_container_credentials.py"
    path.write_text(_credential_server_source(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("athena_container_credentials", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_helper(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _identity(tmp_path: Path) -> Path:
    directory = tmp_path / "identity"
    directory.mkdir()
    (directory / "tls.crt").write_text("cert\n", encoding="utf-8")
    (directory / "tls.key").write_text("key\n", encoding="utf-8")
    (directory / "trust-anchor-arn").write_text(
        " arn:aws:rolesanywhere:us-west-2:1:trust-anchor/a \n",
        encoding="utf-8",
    )
    (directory / "profile-arn").write_text(
        "arn:aws:rolesanywhere:us-west-2:1:profile/b\n",
        encoding="utf-8",
    )
    (directory / "role-arn").write_text(
        "\tarn:aws:iam::1:role/grow-room-grafana-reader\n",
        encoding="utf-8",
    )
    return directory


def _serve(module):
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_parse_expiration_accepts_roles_anywhere_timestamps(tmp_path: Path):
    module = _load_credential_server(tmp_path)
    zulu = module.parse_expiration("2099-01-01T00:00:00Z")
    fractional = module.parse_expiration("2099-01-01T00:00:00.123Z")
    offset = module.parse_expiration("2099-01-01T00:00:00.123456-07:00")
    assert zulu == fractional
    assert zulu.tzinfo is not None
    assert offset.utcoffset() is not None
    doc = module.to_container_credentials(
        {
            "AccessKeyId": "ASIATEST",
            "SecretAccessKey": "secret-value",
            "SessionToken": "session-token",
            "Expiration": "2099-01-01T00:00:00.123Z",
        }
    )
    assert doc["Token"] == "session-token"
    assert "SessionToken" not in doc


def test_container_credential_server_serves_the_ecs_document(tmp_path: Path):
    module = _load_credential_server(tmp_path)
    calls = tmp_path / "calls"
    document = {
        "Version": 1,
        "AccessKeyId": "ASIATEST",
        "SecretAccessKey": "secret-value",
        "SessionToken": "session-token",
        "Expiration": "2099-01-01T00:00:00Z",
    }
    helper = tmp_path / "aws_signing_helper"
    _write_helper(
        helper,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                f"path = pathlib.Path({str(calls)!r})",
                "with path.open('a', encoding='utf-8') as handle:",
                "    handle.write('\\n'.join(sys.argv) + '\\n---\\n')",
                f"print(json.dumps({document!r}))",
                "",
            ]
        ),
    )
    module.HELPER = str(helper)
    module.IDENTITY = str(_identity(tmp_path))
    module.CACHE = module._Cache()
    server = _serve(module)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/credentials", timeout=5) as response:
            body = json.load(response)
            assert response.status == 200
        assert body == {
            "AccessKeyID": "ASIATEST",
            "SecretAccessKey": "secret-value",
            "Token": "session-token",
            "Expiration": "2099-01-01T00:00:00Z",
        }
        assert "SessionToken" not in body
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/credentials", timeout=5) as again:
            assert json.load(again)["Token"] == "session-token"
        recorded = calls.read_text(encoding="utf-8")
        assert recorded.count("\n---\n") == 1
        assert "credential-process" in recorded
        assert "arn:aws:iam::1:role/grow-room-grafana-reader" in recorded
        assert "arn:aws:rolesanywhere:us-west-2:1:trust-anchor/a" in recorded
    finally:
        server.shutdown()
        server.server_close()


def test_container_credential_server_hides_failed_helper_stdout(tmp_path: Path):
    module = _load_credential_server(tmp_path)
    helper = tmp_path / "aws_signing_helper"
    _write_helper(
        helper,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "sys.stdout.write('SECRETKEYMATERIAL')",
                "sys.stderr.write('rolesanywhere unreachable')",
                "raise SystemExit(1)",
                "",
            ]
        ),
    )
    module.HELPER = str(helper)
    module.IDENTITY = str(_identity(tmp_path))
    module.CACHE = module._Cache()
    server = _serve(module)
    port = server.server_address[1]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/credentials", timeout=5)
        raise AssertionError("expected HTTP 500")
    except urllib.error.HTTPError as exc:
        payload = json.load(exc)
        assert exc.code == 500
        assert payload["code"] == "CredentialProcessFailed"
        assert payload["message"] == "rolesanywhere unreachable"
        assert "SECRETKEYMATERIAL" not in json.dumps(payload)
    finally:
        server.shutdown()
        server.server_close()
