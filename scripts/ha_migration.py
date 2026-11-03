# scripts/ha_migration.py
"""Decisions for moving one Home Assistant config between the house and EKS.

The PowerShell orchestrator in aws-poc.ps1 calls this for argument-free
decisions: single-copy guards, abort-on-backup-failure, retention, and
upload checks. It prints JSON on stdout. It does not print archive bytes,
tokens, or object bodies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

HOME_COMPOSE_SERVICE = "homeassistant"
HOME_CONFIG_DIR = "ha-config"
HOME_DB_NAME = "home-assistant_v2.db"
BACKUP_PREFIX = "ha-backups/"
DEFAULT_KEEP = 5
TELEMETRY_BUCKET = "grow-room-telemetry-590183769702"
KMS_ALIAS = "alias/grow-room/telemetry"
BACKUP_ROLE_NAME = "grow-room-ha-backup"
NAMESPACE = "grow-room"
DEPLOYMENT = "home-assistant"
CONTAINER = "home-assistant"
HA_OBJECT = "ha-long-lived-token"
HA_URL = "http://home-assistant.grow-room.svc.cluster.local:8123"

_RESULT_KEYS = (
    "action",
    "reason",
    "stop_home",
    "start_home",
    "start_eks_ha",
    "stop_eks",
    "restart_eks",
    "continue_up",
    "continue_teardown",
    "skip_backup",
)


def constants() -> dict:
    return {
        "compose_service": HOME_COMPOSE_SERVICE,
        "config_dir": HOME_CONFIG_DIR,
        "db_name": HOME_DB_NAME,
        "backup_prefix": BACKUP_PREFIX,
        "default_keep": DEFAULT_KEEP,
        "bucket": TELEMETRY_BUCKET,
        "kms_alias": KMS_ALIAS,
        "role_name": BACKUP_ROLE_NAME,
        "namespace": NAMESPACE,
        "deployment": DEPLOYMENT,
        "container": CONTAINER,
        "secret_name": HA_OBJECT,
        "ha_url": HA_URL,
    }


def _result(**kwargs: object) -> dict:
    base: dict[str, object] = {
        "action": "refuse",
        "reason": "",
        "stop_home": False,
        "start_home": False,
        "start_eks_ha": False,
        "stop_eks": False,
        "restart_eks": False,
        "continue_up": False,
        "continue_teardown": False,
        "skip_backup": False,
    }
    base.update(kwargs)
    return {key: base[key] for key in _RESULT_KEYS}


def _both_running_reason() -> str:
    return (
        "Home Assistant is running at home and on EKS. "
        "Stop one copy before moving anything. "
        "The AC Infinity integration must not log in from two places. "
        "Nothing was changed."
    )


def plan_up(state: dict) -> dict:
    """Choose the next up step. with_ha false is the existing plain up."""
    if not state.get("with_ha"):
        return _result(
            action="plain-up",
            continue_up=True,
            reason="plain up does not stop, back up, or start Home Assistant",
        )

    home = bool(state.get("home_running"))
    eks = bool(state.get("eks_running"))
    phase = str(state.get("phase") or "preflight")
    backup_ok = bool(state.get("backup_ok"))
    upload_ok = bool(state.get("upload_verified"))
    stopped_by_us = bool(state.get("home_stopped_by_us"))
    was_running = bool(state.get("was_running"))
    already = bool(state.get("already_on_eks"))

    if home and eks:
        return _result(action="refuse", reason=_both_running_reason())

    if phase == "preflight":
        if state.get("dry_run"):
            return _result(
                action="dry-run",
                reason="dry run does not stop Home Assistant, upload a backup, or apply Terraform",
            )
        if eks and not home:
            return _result(
                action="already-on-eks",
                skip_backup=True,
                continue_up=True,
                reason="Home Assistant is already on EKS and stopped at home. Skipping the backup.",
            )
        return _result(
            action="backup-then-move",
            stop_home=home,
            reason="Stop home Home Assistant, back up ha-config, and verify S3 before Terraform.",
        )

    if phase == "after-backup":
        if not backup_ok or not upload_ok:
            return _result(
                action="abort-restart-home",
                start_home=stopped_by_us or was_running,
                start_eks_ha=False,
                continue_up=False,
                reason=(
                    "Backup failed or the upload could not be verified. "
                    "Restarting Home Assistant at home when this move stopped it. "
                    "EKS Home Assistant will not start, and Terraform will not apply."
                ),
            )
        return _result(
            action="continue-up",
            continue_up=True,
            reason="Backup object verified.",
        )

    if phase == "before-eks":
        if home:
            return _result(
                action="refuse",
                start_eks_ha=False,
                reason=(
                    "Refusing to start Home Assistant on EKS "
                    "while home Home Assistant is still running."
                ),
            )
        if already:
            return _result(
                action="start-eks",
                start_eks_ha=True,
                continue_up=True,
                reason="Home copy is stopped. Helm upgrade keeps the single EKS copy.",
            )
        if not backup_ok or not upload_ok:
            return _result(
                action="abort-restart-home",
                start_home=stopped_by_us or was_running,
                start_eks_ha=False,
                continue_up=False,
                reason="Refusing to start Home Assistant on EKS without a verified backup.",
            )
        return _result(
            action="start-eks",
            start_eks_ha=True,
            continue_up=True,
            reason="Home Home Assistant is stopped and the backup is verified.",
        )

    return _result(action="refuse", reason=f"unknown up phase: {phase}")


def plan_down(state: dict) -> dict:
    """Choose the next down step. No move in progress continues the old teardown."""
    home = bool(state.get("home_running"))
    eks = bool(state.get("eks_running"))
    ha_on_eks = bool(state.get("ha_on_eks"))
    phase = str(state.get("phase") or "preflight")
    location = str(state.get("location") or "")
    backup_ok = bool(state.get("backup_ok"))
    upload_ok = bool(state.get("upload_verified"))
    restore_ok = bool(state.get("restore_ok"))
    moved = ha_on_eks or location in {"eks", "moving"}

    if home and eks:
        return _result(
            action="refuse",
            continue_teardown=False,
            reason=_both_running_reason() + " Teardown did not start.",
        )

    if phase == "preflight":
        if location == "moving" and not eks:
            return _result(
                action="restart-home-then-down",
                start_home=not home,
                stop_eks=ha_on_eks,
                continue_teardown=True,
                reason=(
                    "The move stopped home Home Assistant before the EKS copy was serving. "
                    "Stop any EKS copy, start home, then continue the existing teardown."
                ),
            )
        if not eks and moved:
            return _result(
                action="restore-from-s3",
                continue_teardown=False,
                reason=(
                    "The EKS Home Assistant process is not running. "
                    "Restore the recorded backup at home before teardown."
                ),
            )
        if not moved:
            return _result(
                action="plain-down",
                continue_teardown=True,
                reason="No Home Assistant move is in progress.",
            )
        return _result(
            action="backup-eks",
            continue_teardown=False,
            reason="Back up the EKS Home Assistant config and verify it before stopping that copy.",
        )

    if phase == "after-eks-backup":
        if not backup_ok or not upload_ok:
            return _result(
                action="abort-keep-eks",
                continue_teardown=False,
                reason=(
                    "EKS backup failed or the upload could not be verified. "
                    "Leaving Home Assistant on EKS. Home was not started. Teardown did not start."
                ),
            )
        return _result(
            action="stop-eks-then-restore",
            stop_eks=True,
            continue_teardown=False,
            reason="Backup verified. Stop EKS Home Assistant before restoring the home copy.",
        )

    if phase == "before-start-home":
        if eks:
            return _result(
                action="refuse",
                start_home=False,
                continue_teardown=False,
                reason=(
                    "Refusing to start home Home Assistant "
                    "while EKS Home Assistant is still running."
                ),
            )
        if not restore_ok:
            return _result(
                action="abort-no-teardown",
                restart_eks=True,
                continue_teardown=False,
                reason=(
                    "Restore at home failed. Home Assistant was not started. "
                    "Teardown did not start. Start the EKS copy again if it was scaled to zero."
                ),
            )
        return _result(
            action="start-home",
            start_home=True,
            continue_teardown=False,
            reason="Config restored and EKS Home Assistant is stopped.",
        )

    if phase == "after-home-started":
        if not home:
            return _result(
                action="abort-no-teardown",
                continue_teardown=False,
                reason="Home Home Assistant did not start. Teardown did not start.",
            )
        return _result(
            action="teardown",
            continue_teardown=True,
            reason="Home Home Assistant is running. Continue the existing teardown.",
        )

    return _result(
        action="refuse",
        continue_teardown=False,
        reason=f"unknown down phase: {phase}",
    )


def object_key(when: datetime | None = None) -> str:
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    stamp = moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{BACKUP_PREFIX}{stamp}.tar.gz"


def _kms_id(value: str) -> str:
    text = value.strip()
    marker = "/key/"
    if marker in text:
        return text.split(marker, 1)[1]
    return text


def verify_head(payload: dict) -> dict:
    """Confirm a HeadObject matches the local archive. Reasons omit checksum bytes."""
    head = payload.get("head") or {}
    if not isinstance(head, dict):
        return {"ok": False, "reason": "head object missing"}
    try:
        local_size = int(payload["local_size"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reason": "local size missing"}
    local_sum = str(payload.get("local_sha256_b64") or "")
    expected = str(payload.get("expected_kms_key_arn") or "")
    reasons: list[str] = []
    try:
        remote_size = int(head.get("ContentLength"))
    except (TypeError, ValueError):
        remote_size = -1
    if remote_size != local_size:
        reasons.append("size mismatch")
    if head.get("ServerSideEncryption") != "aws:kms":
        reasons.append("not kms encrypted")
    remote_sum = str(head.get("ChecksumSHA256") or "")
    if not local_sum or remote_sum != local_sum:
        reasons.append("checksum mismatch")
    remote_key = str(head.get("SSEKMSKeyId") or "")
    if not remote_key:
        reasons.append("missing kms key id")
    elif expected and _kms_id(expected) != _kms_id(remote_key):
        reasons.append("kms key mismatch")
    return {"ok": not reasons, "reason": "; ".join(reasons)}


def keys_to_delete(objects: list[dict], keep: int) -> list[str]:
    """Return older ha-backups keys. Never returns a key outside that prefix."""
    if keep < 1:
        raise ValueError("keep must be >= 1")
    rows: list[dict] = []
    for obj in objects:
        key = str(obj.get("key") or "")
        if not key.startswith(BACKUP_PREFIX) or key.endswith("/") or ".." in key:
            continue
        rows.append({"key": key, "last_modified": str(obj.get("last_modified") or "")})
    rows.sort(key=lambda item: (item["last_modified"], item["key"]), reverse=True)
    return [item["key"] for item in rows[keep:]]


def sha256_b64(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")


def _db_member(name: str) -> bool:
    rel = name.replace("\\", "/").lstrip("./")
    return rel == HOME_DB_NAME or rel.endswith("/" + HOME_DB_NAME)


def archive_contains_db(path: Path) -> bool:
    with tarfile.open(path, "r:gz") as tar:
        return any(_db_member(member.name) for member in tar.getmembers() if member.isfile())


def pack_config(src: Path, dest: Path) -> dict:
    """Tar the config folder. Refuse when home-assistant_v2.db is absent."""
    src = src.resolve()
    dest = dest.resolve()
    db = src / HOME_DB_NAME
    if not db.is_file():
        raise SystemExit(f"backup refused: {HOME_DB_NAME} is not in the config folder")
    if dest == src or src in dest.parents:
        raise SystemExit("backup refused: archive path is inside the config folder")
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(src.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            tar.add(path, arcname=path.relative_to(src).as_posix(), recursive=False)
            count += 1
    if not archive_contains_db(dest):
        dest.unlink(missing_ok=True)
        raise SystemExit(f"backup refused: archive does not contain {HOME_DB_NAME}")
    return {"files": count, "bytes": dest.stat().st_size}


def safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    db = dest / HOME_DB_NAME
    if not db.is_file() or db.stat().st_size <= 0:
        raise SystemExit(f"archive is missing {HOME_DB_NAME}")


def restore_home(archive: Path, config: Path) -> dict:
    """Replace the config folder only after the archive is checked."""
    archive = archive.resolve()
    config = config.resolve()
    staging = config.parent / (config.name + ".staging")
    previous = config.parent / (config.name + ".previous")
    if staging.exists():
        shutil.rmtree(staging)
    safe_extract(archive, staging)
    if previous.exists():
        shutil.rmtree(previous)
    if config.exists():
        os.rename(config, previous)
    try:
        os.rename(staging, config)
    except OSError:
        if previous.exists() and not config.exists():
            os.rename(previous, config)
        raise
    db = config / HOME_DB_NAME
    return {"ok": True, "bytes": db.stat().st_size}


def _load(path: str) -> dict:
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit("input must be a JSON object")
    return data


def _emit(payload: dict) -> int:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ha_migration.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("constants")

    key = sub.add_parser("object-key")
    key.add_argument("--timestamp", default="")

    pack = sub.add_parser("pack")
    pack.add_argument("--config", required=True)
    pack.add_argument("--output", required=True)

    check = sub.add_parser("check-archive")
    check.add_argument("--archive", required=True)

    restore = sub.add_parser("restore-home")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--config", required=True)

    for name in ("plan-up", "plan-down", "prune", "verify-head"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "constants":
        return _emit(constants())
    if args.cmd == "object-key":
        when = None
        if args.timestamp:
            text = args.timestamp.replace("Z", "+00:00")
            when = datetime.fromisoformat(text)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
        return _emit({"key": object_key(when)})
    if args.cmd == "pack":
        return _emit(pack_config(Path(args.config), Path(args.output)))
    if args.cmd == "check-archive":
        ok = archive_contains_db(Path(args.archive))
        if not ok:
            sys.stderr.write(f"archive is missing {HOME_DB_NAME}\n")
            return 1
        return _emit({"ok": True})
    if args.cmd == "restore-home":
        return _emit(restore_home(Path(args.archive), Path(args.config)))
    payload = _load(args.input)
    if args.cmd == "plan-up":
        return _emit(plan_up(payload))
    if args.cmd == "plan-down":
        return _emit(plan_down(payload))
    if args.cmd == "verify-head":
        return _emit(verify_head(payload))
    if args.cmd == "prune":
        keep = int(payload.get("keep") or DEFAULT_KEEP)
        keys = payload.get("keys") or []
        if not isinstance(keys, list):
            raise SystemExit("keys must be a list")
        return _emit({"delete": keys_to_delete(keys, keep)})
    raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0) from None
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1) from None
