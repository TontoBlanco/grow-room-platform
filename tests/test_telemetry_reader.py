"""The Grafana reader is a separate role. The shipper stays write-only."""

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
    assert "grafana-athena-datasource 3.4.2" in VALUES
    assert "http://127.0.0.1:9911" in VALUES
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
        "grafana-athena-datasource 3.4.2",
        "http://127.0.0.1:9911",
        "terraform -chdir=infra/telemetry",
        "helm upgrade --install monitoring",
        "C:\\src\\grow-room-pki\\ca.pem",
        "/mnt/c/src/grow-room-pki/ca.pem",
        "aws sts get-caller-identity --query Account --output text",
    ):
        assert needle in DOC
    for placeholder in ("<ACCOUNT", "YOUR_", "TODO", "changeme", "example.com"):
        assert placeholder not in DOC
