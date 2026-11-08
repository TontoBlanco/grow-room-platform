# scripts/ha_migration.py
"""Decisions for moving one Home Assistant config between the house and EKS.

The PowerShell orchestrator in aws-poc.ps1 calls this for argument-free
decisions: single-copy guards, abort-on-backup-failure, retention, and
upload checks. It also maps a Docker /config mount onto a Windows path and
builds the wsl tar argument list for a wsl.localhost UNC folder. It prints
JSON on stdout. It does not print archive bytes, tokens, or object bodies.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
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


_DISTRO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DOCKER_DESKTOP = "/run/desktop/mnt/host/"


def _as_list(value: object) -> list:
    """PowerShell 5.1 ConvertTo-Json unwraps a one-element array into an object."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _reject_segment(part: str) -> None:
    if not part or part in {".", ".."}:
        raise ValueError("config path has an empty or relative segment")
    if _CONTROL_RE.search(part):
        raise ValueError("config path has a control character")


def _looks_windows(path: str) -> bool:
    text = path.strip().replace("/", "\\")
    if text.startswith("\\\\"):
        return True
    return len(text) >= 2 and text[0].isalpha() and text[1] == ":"


def normalize_windows_path(path: str) -> str:
    text = path.strip().replace("/", "\\")
    if text.startswith("\\\\"):
        rest = text[2:].replace("\\\\", "\\")
        text = "\\\\" + rest
    else:
        text = text.replace("\\\\", "\\")
    if len(text) > 3:
        text = text.rstrip("\\")
    return text


def _drive_tail(rest: str) -> str | None:
    if not rest or not rest[0].isalpha():
        return None
    if len(rest) > 1 and rest[1] != "/":
        return None
    win = rest[0].upper() + ":"
    tail = rest[1:]
    if tail.startswith("/"):
        win += tail.replace("/", "\\")
    return win


def _docker_desktop_drive(linux: str) -> str | None:
    if not linux.lower().startswith(_DOCKER_DESKTOP):
        return None
    return _drive_tail(linux[len(_DOCKER_DESKTOP) :])


def _mnt_drive(linux: str) -> str | None:
    if not linux.lower().startswith("/mnt/"):
        return None
    return _drive_tail(linux[len("/mnt/") :])


def needs_wsl_distro(source: str) -> bool:
    """True when a Docker mount source has to be joined to the default distro."""
    linux = source.strip().replace("\\", "/")
    if not linux.startswith("/"):
        return False
    if _docker_desktop_drive(linux) is not None or _mnt_drive(linux) is not None:
        return False
    return True


def _linux_to_unc(distro: str, linux: str) -> str:
    parts: list[str] = []
    for part in linux.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("config source must not contain ..")
        _reject_segment(part)
        parts.append(part)
    suffix = "\\".join(parts)
    if suffix:
        return "\\\\wsl.localhost\\" + distro + "\\" + suffix
    return "\\\\wsl.localhost\\" + distro


def map_config_path(source: str, distro: str = "") -> str:
    """Map a docker Mount.Source (or an explicit path) to a Windows path.

    Windows paths and existing UNC paths stay as they are. Docker Desktop
    host mounts and /mnt/<drive> become a drive letter. Every other absolute
    Linux path is the default distro's filesystem, exposed as
    \\\\wsl.localhost\\<distro>\\...
    """
    raw = source.strip()
    if not raw:
        raise ValueError("config source is empty")
    if _looks_windows(raw):
        return normalize_windows_path(raw)
    linux = raw.replace("\\", "/")
    if not linux.startswith("/"):
        raise ValueError("config source is not an absolute path")
    desktop = _docker_desktop_drive(linux)
    if desktop is not None:
        return desktop
    mounted = _mnt_drive(linux)
    if mounted is not None:
        return mounted
    name = distro.strip()
    if not _DISTRO_RE.fullmatch(name):
        raise ValueError("WSL distro name is missing or invalid")
    return _linux_to_unc(name, linux)


def decode_wsl_listing(payload: bytes) -> str:
    """Decode `wsl.exe -l -q`. Console output is UTF-16LE; a pipe may be UTF-8."""
    data = payload
    if data.startswith(b"\xff\xfe") or (len(data) >= 4 and data[1] == 0 and data[3] == 0):
        if data.startswith(b"\xff\xfe"):
            data = data[2:]
        if len(data) % 2 == 1:
            data = data[:-1]
        text = data.decode("utf-16-le", errors="replace")
    else:
        text = data.decode("utf-8-sig")
    return text.replace("\x00", "").replace("\ufeff", "")


def default_distro_name(listing: str) -> str:
    """First distribution from `wsl -l -q`. That command prints the default first."""
    for line in listing.splitlines():
        name = line.strip().lstrip("\ufeff")
        if name.startswith("*"):
            name = name[1:].strip()
        name = name.replace("(Default)", "").strip()
        if _DISTRO_RE.fullmatch(name):
            return name
    raise ValueError("wsl -l -q did not list a distribution")


def wsl_default_distro(payload: bytes) -> str:
    return default_distro_name(decode_wsl_listing(payload))


def select_home_container(containers: object, service: str = HOME_COMPOSE_SERVICE) -> dict:
    """Pick the Home Assistant container and its /config mount source.

    Prefer a running Compose service match, then any running name match, then
    the same order for a stopped container. `down` still has to find the
    folder after this script has stopped the container.
    """
    rows: list[dict] = []
    for item in _as_list(containers):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lstrip("/")
        if not name or name.startswith("-") or any(ch in name for ch in "\r\n\t"):
            continue
        rows.append(
            {
                "name": name,
                "running": _as_bool(item.get("running")),
                "service": str(item.get("service") or "").strip(),
                "source": str(item.get("source") or "").strip(),
            }
        )

    def rank(row: dict) -> tuple | None:
        wanted = service.lower()
        labeled = row["service"].lower() == wanted
        named = wanted in row["name"].lower()
        if not labeled and not named:
            return None
        return (0 if row["running"] else 1, 0 if labeled else 1, row["name"])

    ranked: list[tuple[tuple, dict]] = []
    for row in rows:
        score = rank(row)
        if score is not None:
            ranked.append((score, row))
    if not ranked:
        return {"name": "", "running": False, "source": "", "service": ""}
    ranked.sort(key=lambda item: item[0])
    best = ranked[0][1]
    return {
        "name": best["name"],
        "running": best["running"],
        "source": best["source"],
        "service": best["service"],
    }


def resolve_config_path(payload: dict) -> dict:
    """Choose the config folder. Explicit wins, then the container mount, then the repo."""
    explicit = str(payload.get("explicit") or "").strip()
    mount = str(payload.get("mount_source") or "").strip()
    distro = str(payload.get("distro") or "").strip()
    repo = str(payload.get("repo_config") or "").strip()
    if explicit:
        chosen = explicit
        origin = "explicit"
    elif mount:
        chosen = mount
        origin = "container-mount"
    else:
        if not repo:
            raise ValueError("repo config path is empty")
        path = normalize_windows_path(repo) if _looks_windows(repo) else repo
        return {"path": path, "origin": "repo-default", "need_distro": False}
    if _looks_windows(chosen):
        return {
            "path": normalize_windows_path(chosen),
            "origin": origin,
            "need_distro": False,
        }
    linux = chosen.replace("\\", "/")
    if not linux.startswith("/"):
        return {"path": chosen, "origin": origin, "need_distro": False}
    if needs_wsl_distro(linux) and not _DISTRO_RE.fullmatch(distro):
        return {"path": "", "origin": origin, "need_distro": True}
    return {
        "path": map_config_path(linux, distro),
        "origin": origin,
        "need_distro": False,
    }


def windows_path_to_wsl(path: str) -> str:
    """C:\\Users\\a\\ha.tar.gz -> /mnt/c/Users/a/ha.tar.gz. WSL tar writes the archive there."""
    text = normalize_windows_path(path)
    if len(text) < 2 or text[1] != ":" or not text[0].isalpha():
        raise ValueError("path must be a Windows drive path so WSL tar can write it")
    letter = text[0].lower()
    rest = text[2:].lstrip("\\")
    parts: list[str] = []
    for part in rest.split("\\"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path must not contain ..")
        _reject_segment(part)
        parts.append(part)
    suffix = "/".join(parts)
    if suffix:
        return f"/mnt/{letter}/{suffix}"
    return f"/mnt/{letter}"


def is_wsl_unc(path: str) -> bool:
    text = path.strip().replace("/", "\\")
    return text.lower().startswith("\\\\wsl.localhost\\")


def split_wsl_unc(path: str) -> tuple[str, str]:
    """\\\\wsl.localhost\\Ubuntu\\home\\colem\\ha-config -> (Ubuntu, /home/colem/ha-config)."""
    text = normalize_windows_path(path)
    prefix = "\\\\wsl.localhost\\"
    if not text.lower().startswith(prefix):
        raise ValueError("config path is not a \\\\wsl.localhost path")
    rest = text[len(prefix) :]
    distro, _sep, tail = rest.partition("\\")
    if not _DISTRO_RE.fullmatch(distro):
        raise ValueError("WSL distro name is missing or invalid")
    parts: list[str] = []
    if tail:
        for part in tail.split("\\"):
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("config path must not contain ..")
            _reject_segment(part)
            parts.append(part)
    return distro, "/" + "/".join(parts)


def _linux_child(parent: str, name: str) -> str:
    if parent == "/":
        return "/" + name
    return parent.rstrip("/") + "/" + name


def _linux_parent_name(linux: str) -> tuple[str, str]:
    stripped = linux.rstrip("/")
    if stripped in ("", "/"):
        raise ValueError("refusing to archive the distro root")
    parent, _sep, name = stripped.rpartition("/")
    if not name:
        raise ValueError("config path has no folder name")
    _reject_segment(name)
    if parent == "":
        parent = "/"
    return parent, name


def _reject_nested(outer: str, inner: str) -> None:
    left = outer.rstrip("/") or "/"
    right = inner.rstrip("/") or "/"
    if right == left or right.startswith(left + "/"):
        raise ValueError("archive path is inside the config folder")


def archive_plan(config: str, archive: str, staged: str = "") -> dict:
    """Argument vectors for packing or restoring one config folder.

    A drive-letter folder stays on the Python packer. A \\\\wsl.localhost path
    is tarred inside that distro. The gzip file is a Windows temp path, which
    WSL sees under /mnt/<drive>. PowerShell must not pipe the bytes: Windows
    PowerShell 5.1 corrupts binary pipeline output.
    """
    empty = {"use_wsl": False, "distro": "", "linux_config": "", "pack": [], "steps": []}
    if not is_wsl_unc(config):
        return empty
    distro, linux_config = split_wsl_unc(config)
    linux_archive = windows_path_to_wsl(archive)
    _reject_nested(linux_config, linux_archive)
    parent, name = _linux_parent_name(linux_config)
    staging = _linux_child(parent, name + ".staging")
    previous = _linux_child(parent, name + ".previous")
    db_path = _linux_child(staging, HOME_DB_NAME)
    pack = [
        "tar",
        "-C",
        linux_config,
        "-czf",
        linux_archive,
        "--one-file-system",
        "--exclude=*.sock",
        ".",
    ]
    steps: list[dict] = []
    if staged.strip():
        linux_staged = windows_path_to_wsl(staged).rstrip("/") + "/."
        _reject_nested(linux_config, linux_staged)
        # Direct mv arguments. Windows PowerShell 5.1 expands $1 and $2 in a
        # bash -c script before bash starts, so those paths never reached mv.
        # Rollback uses mv -T so a leftover .previous is not placed inside a
        # config folder that is still present.
        steps = [
            {"argv": ["rm", "-rf", staging], "when": "always"},
            {"argv": ["mkdir", "-p", staging], "when": "always"},
            {"argv": ["cp", "-a", linux_staged, staging + "/"], "when": "always"},
            {"argv": ["/usr/bin/test", "-s", db_path], "when": "always"},
            {"argv": ["rm", "-rf", previous], "when": "always"},
            {"argv": ["mv", linux_config, previous], "when": "always"},
            {"argv": ["mv", staging, linux_config], "when": "always"},
            {"argv": ["mv", "-T", previous, linux_config], "when": "rollback"},
        ]
    return {
        "use_wsl": True,
        "distro": distro,
        "linux_config": linux_config,
        "pack": pack,
        "steps": steps,
    }


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

    wsl_distro = sub.add_parser("wsl-distro")
    wsl_distro.add_argument("--base64", required=True)

    stage = sub.add_parser("stage-archive")
    stage.add_argument("--archive", required=True)
    stage.add_argument("--dest", required=True)

    for name in (
        "plan-up",
        "plan-down",
        "prune",
        "verify-head",
        "resolve-config",
        "select-container",
        "archive-plan",
    ):
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
    if args.cmd == "wsl-distro":
        try:
            raw = base64.b64decode(args.base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SystemExit("wsl listing is not base64") from exc
        return _emit({"distro": wsl_default_distro(raw)})
    if args.cmd == "stage-archive":
        safe_extract(Path(args.archive), Path(args.dest))
        return _emit({"ok": True})
    payload = _load(args.input)
    if args.cmd == "plan-up":
        return _emit(plan_up(payload))
    if args.cmd == "plan-down":
        return _emit(plan_down(payload))
    if args.cmd == "verify-head":
        return _emit(verify_head(payload))
    if args.cmd == "resolve-config":
        return _emit(resolve_config_path(payload))
    if args.cmd == "select-container":
        return _emit(select_home_container(payload.get("containers")))
    if args.cmd == "archive-plan":
        return _emit(
            archive_plan(
                str(payload.get("config") or ""),
                str(payload.get("archive") or ""),
                str(payload.get("staged") or ""),
            )
        )
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
