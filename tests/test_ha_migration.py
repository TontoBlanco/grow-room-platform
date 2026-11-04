"""Phase 8 decisions: one Home Assistant copy, abort when the backup is bad."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ha_migration.py"
POC = ROOT / "scripts" / "aws-poc.ps1"
HELPER = ROOT / "scripts" / "aws-poc-ha.ps1"
COMPOSE = ROOT / "docker-compose.yml"
PACK = ROOT / "charts" / "home-assistant" / "files" / "pack_config.py"
RESTORE = ROOT / "charts" / "home-assistant" / "files" / "restore.sh"


def load():
    spec = importlib.util.spec_from_file_location("ha_migration", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_constants_match_compose_service_and_volume():
    ha = load()
    text = COMPOSE.read_text(encoding="utf-8")
    assert f"{ha.HOME_COMPOSE_SERVICE}:" in text
    assert f"./{ha.HOME_CONFIG_DIR}:/config" in text
    assert ha.HOME_DB_NAME == "home-assistant_v2.db"
    assert ha.TELEMETRY_BUCKET == "grow-room-telemetry-590183769702"
    assert ha.KMS_ALIAS == "alias/grow-room/telemetry"
    assert ha.DEFAULT_KEEP == 5
    assert ha.BACKUP_PREFIX == "ha-backups/"


def test_scripts_are_utf8_without_bom_and_powershell_is_ascii():
    for path in (SCRIPT, POC, HELPER, PACK, RESTORE):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path.name
        raw.decode("utf-8")
    for path in (POC, HELPER):
        assert all(byte < 128 for byte in path.read_bytes()), path.name


def test_argument_parsing_surface():
    text = POC.read_text(encoding="utf-8")
    assert '[ValidateSet("up", "verify", "down")]' in text
    assert "[switch]$WithHA" in text
    assert "[switch]$DryRun" in text
    assert "[int]$HaBackupKeep = 5" in text
    assert "[string]$HaConfigPath" in text
    assert "Invoke-UpStack" in text
    assert "if (-not $WithHA)" in text
    assert "enable_ha_migration=true" in text
    assert text.index("if ($WithHA)") < text.index("enable_ha_migration=true")
    helper = HELPER.read_text(encoding="utf-8")
    assert "abort-restart-home" in helper
    assert "Start-HomeHa" in helper
    assert "Remove-AvailableEnis" in text
    assert "Invoke-HaReturnHomeIfNeeded" in text
    # Plain up returns before the Home Assistant prepare function.
    up = text.split("function Do-Up", 1)[1].split("function Invoke-UpStack", 1)[0]
    assert "Invoke-WithHaPrepare" in up
    assert up.index("if (-not $WithHA)") < up.index("Invoke-WithHaPrepare")
    assert "DRY RUN" in up


def test_plain_up_does_not_switch_sensor_source_in_git():
    values = (ROOT / "charts" / "sensor-service" / "values-eks.yaml").read_text(encoding="utf-8")
    assert "SENSOR_SOURCE: homeassistant" not in values
    assert "homeassistant" not in values


def test_backup_policy_is_prefix_scoped():
    text = (ROOT / "infra" / "telemetry" / "ha_backup.tf").read_text(encoding="utf-8")
    assert "s3:*" not in text
    assert "kms:*" not in text
    assert "ha-backups/*" in text
    assert "s3:PutObject" in text
    assert "s3:GetObject" in text
    assert "s3:DeleteObject" in text
    assert "s3:ListBucket" in text
    assert "kms:GenerateDataKey" in text
    assert "kms:Decrypt" in text
    lifecycle = (ROOT / "infra" / "telemetry" / "main.tf").read_text(encoding="utf-8")
    assert "abort-incomplete-ha-backup-uploads" in lifecycle
    assert "ha-backups/" in lifecycle
    flag = (ROOT / "infra" / "aws-poc" / "ha_migration.tf").read_text(encoding="utf-8")
    assert "var.enable_ha_migration" in flag
    assert "grow-room-ha-backup" in flag


def test_object_key_shape():
    ha = load()
    key = ha.object_key(datetime(2026, 11, 3, 20, 30, 45, tzinfo=UTC))
    assert key == "ha-backups/20261103T203045Z.tar.gz"


def test_pack_requires_database_and_does_not_print_bytes(tmp_path, capsys):
    ha = load()
    src = tmp_path / "ha-config"
    src.mkdir()
    (src / "secrets.yaml").write_text("token: super-secret-value\n", encoding="utf-8")
    try:
        ha.pack_config(src, tmp_path / "out.tar.gz")
    except SystemExit as exc:
        assert ha.HOME_DB_NAME in str(exc)
    else:
        raise AssertionError("pack should refuse a folder with no database")
    captured = capsys.readouterr()
    assert "super-secret-value" not in captured.out
    assert "super-secret-value" not in captured.err

    (src / ha.HOME_DB_NAME).write_bytes(b"sqlite-bytes")
    dest = tmp_path / "good.tar.gz"
    summary = ha.pack_config(src, dest)
    assert summary["files"] == 2
    assert ha.archive_contains_db(dest)
    with tarfile.open(dest, "r:gz") as tar:
        member = tar.extractfile("secrets.yaml")
        assert member is not None
        assert b"super-secret-value" in member.read()
    captured = capsys.readouterr()
    assert "super-secret-value" not in captured.out


def test_restore_home_replaces_folder_only_after_the_db_is_present(tmp_path):
    ha = load()
    src = tmp_path / "src"
    src.mkdir()
    (src / ha.HOME_DB_NAME).write_bytes(b"db-v2")
    (src / "configuration.yaml").write_text("name: tent\n", encoding="utf-8")
    archive = tmp_path / "ha.tar.gz"
    ha.pack_config(src, archive)
    dest = tmp_path / "ha-config"
    dest.mkdir()
    (dest / "configuration.yaml").write_text("name: old\n", encoding="utf-8")
    result = ha.restore_home(archive, dest)
    assert result["ok"] is True
    assert (dest / ha.HOME_DB_NAME).read_bytes() == b"db-v2"
    assert "name: tent" in (dest / "configuration.yaml").read_text(encoding="utf-8")
    previous = tmp_path / "ha-config.previous" / "configuration.yaml"
    assert previous.read_text(encoding="utf-8") == "name: old\n"


def test_safe_extract_rejects_path_escape(tmp_path):
    ha = load()
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = tmp_path / "evil.txt"
        payload.write_text("nope", encoding="utf-8")
        tar.add(payload, arcname="../evil.txt")
    try:
        ha.safe_extract(archive, tmp_path / "out")
    except (SystemExit, tarfile.OutsideDestinationError, tarfile.FilterError):
        return
    raise AssertionError("extract should refuse a path escape")


def test_verify_head_accepts_matching_kms_object_and_rejects_the_rest():
    ha = load()
    digest = hashlib.sha256(b"archive").digest()
    checksum = base64.b64encode(digest).decode("ascii")
    arn = "arn:aws:kms:us-west-2:590183769702:key/abc"
    good = {
        "local_size": 12,
        "local_sha256_b64": checksum,
        "expected_kms_key_arn": arn,
        "head": {
            "ContentLength": 12,
            "ServerSideEncryption": "aws:kms",
            "ChecksumSHA256": checksum,
            "SSEKMSKeyId": arn,
        },
    }
    assert ha.verify_head(good)["ok"] is True
    bad_size = json.loads(json.dumps(good))
    bad_size["head"]["ContentLength"] = 3
    size = ha.verify_head(bad_size)
    assert size["ok"] is False
    assert "size" in size["reason"]
    assert checksum not in size["reason"]
    bad_sse = json.loads(json.dumps(good))
    bad_sse["head"]["ServerSideEncryption"] = "AES256"
    assert ha.verify_head(bad_sse)["ok"] is False
    bad_sum = json.loads(json.dumps(good))
    bad_sum["head"]["ChecksumSHA256"] = base64.b64encode(b"x" * 32).decode("ascii")
    mismatch = ha.verify_head(bad_sum)
    assert mismatch["ok"] is False
    assert "checksum" in mismatch["reason"]
    assert checksum not in mismatch["reason"]


def test_prune_keeps_newest_five_and_ignores_other_prefixes():
    ha = load()
    keys = [
        {"key": f"ha-backups/2026110{i}T000000Z.tar.gz", "last_modified": f"2026-11-0{i}T00:00:00Z"}
        for i in range(1, 8)
    ]
    keys.append({"key": "readings/dt=2026-11-01/a.json", "last_modified": "2026-11-09T00:00:00Z"})
    keys.append({"key": "ha-backups/../../secrets", "last_modified": "2026-11-09T00:00:00Z"})
    deleted = ha.keys_to_delete(keys, keep=5)
    assert deleted == [
        "ha-backups/20261102T000000Z.tar.gz",
        "ha-backups/20261101T000000Z.tar.gz",
    ]
    assert ha.keys_to_delete(keys[:5], keep=5) == []


def _up(**kwargs):
    base = {
        "with_ha": True,
        "dry_run": False,
        "phase": "preflight",
        "home_running": True,
        "eks_running": False,
        "backup_ok": False,
        "upload_verified": False,
        "home_stopped_by_us": False,
        "was_running": True,
        "already_on_eks": False,
    }
    base.update(kwargs)
    return load().plan_up(base)


def test_plain_up_plan_does_not_touch_home_assistant():
    plan = _up(with_ha=False)
    assert plan["action"] == "plain-up"
    assert plan["continue_up"] is True
    assert plan["stop_home"] is False
    assert plan["start_eks_ha"] is False
    assert plan["start_home"] is False


def test_dry_run_does_not_stop_or_upload():
    plan = _up(dry_run=True)
    assert plan["action"] == "dry-run"
    assert plan["stop_home"] is False
    assert plan["start_eks_ha"] is False
    assert plan["continue_up"] is False


def test_refuse_when_both_copies_are_running():
    plan = _up(home_running=True, eks_running=True)
    assert plan["action"] == "refuse"
    assert plan["start_eks_ha"] is False
    assert plan["stop_home"] is False
    assert "two places" in plan["reason"]


def test_backup_failure_restarts_home_and_does_not_start_eks():
    for backup_ok, upload_ok in ((False, False), (True, False), (False, True)):
        plan = _up(
            phase="after-backup",
            backup_ok=backup_ok,
            upload_verified=upload_ok,
            home_stopped_by_us=True,
            was_running=True,
        )
        assert plan["action"] == "abort-restart-home"
        assert plan["start_home"] is True
        assert plan["start_eks_ha"] is False
        assert plan["continue_up"] is False


def test_verified_backup_continues_without_starting_eks_yet():
    plan = _up(phase="after-backup", backup_ok=True, upload_verified=True, home_stopped_by_us=True)
    assert plan["action"] == "continue-up"
    assert plan["start_eks_ha"] is False
    assert plan["continue_up"] is True


def test_refuse_eks_start_while_home_is_running():
    plan = _up(phase="before-eks", home_running=True, backup_ok=True, upload_verified=True)
    assert plan["action"] == "refuse"
    assert plan["start_eks_ha"] is False
    assert "still running" in plan["reason"]


def test_start_eks_only_after_home_is_stopped_and_upload_verified():
    blocked = _up(phase="before-eks", home_running=False, backup_ok=False, upload_verified=False)
    assert blocked["start_eks_ha"] is False
    ready = _up(
        phase="before-eks",
        home_running=False,
        backup_ok=True,
        upload_verified=True,
        home_stopped_by_us=True,
    )
    assert ready["action"] == "start-eks"
    assert ready["start_eks_ha"] is True
    assert ready["start_home"] is False


def _down(**kwargs):
    base = {
        "phase": "preflight",
        "home_running": False,
        "eks_running": False,
        "ha_on_eks": False,
        "location": "",
        "backup_ok": False,
        "upload_verified": False,
        "restore_ok": False,
    }
    base.update(kwargs)
    return load().plan_down(base)


def test_plain_down_when_nothing_moved():
    plan = _down()
    assert plan["action"] == "plain-down"
    assert plan["continue_teardown"] is True
    assert plan["start_home"] is False


def test_down_refuses_dual_copy_and_skips_teardown():
    plan = _down(home_running=True, eks_running=True, ha_on_eks=True, location="eks")
    assert plan["action"] == "refuse"
    assert plan["continue_teardown"] is False
    assert plan["start_home"] is False


def test_down_keeps_eks_when_backup_is_not_verified():
    plan = _down(phase="after-eks-backup", ha_on_eks=True, location="eks", eks_running=True)
    assert plan["action"] == "abort-keep-eks"
    assert plan["continue_teardown"] is False
    assert plan["start_home"] is False
    assert plan["stop_eks"] is False


def test_down_refuses_to_start_home_while_eks_is_running():
    plan = _down(
        phase="before-start-home",
        eks_running=True,
        ha_on_eks=True,
        restore_ok=True,
        backup_ok=True,
        upload_verified=True,
    )
    assert plan["action"] == "refuse"
    assert plan["start_home"] is False
    assert plan["continue_teardown"] is False


def test_down_restore_failure_does_not_tear_down():
    plan = _down(phase="before-start-home", eks_running=False, ha_on_eks=True, restore_ok=False)
    assert plan["action"] == "abort-no-teardown"
    assert plan["restart_eks"] is True
    assert plan["start_home"] is False
    assert plan["continue_teardown"] is False


def test_down_starts_home_then_tears_down_only_after_it_is_up():
    start = _down(
        phase="before-start-home",
        restore_ok=True,
        backup_ok=True,
        upload_verified=True,
        eks_running=False,
    )
    assert start["action"] == "start-home"
    assert start["start_home"] is True
    assert start["continue_teardown"] is False
    not_yet = _down(phase="after-home-started", home_running=False)
    assert not_yet["continue_teardown"] is False
    done = _down(phase="after-home-started", home_running=True)
    assert done["action"] == "teardown"
    assert done["continue_teardown"] is True


def test_cli_plan_up_json(tmp_path):
    payload = tmp_path / "in.json"
    payload.write_text(
        json.dumps({"with_ha": True, "phase": "after-backup", "home_stopped_by_us": True}),
        encoding="utf-8",
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "plan-up", "--input", str(payload)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["action"] == "abort-restart-home"
    assert "token" not in proc.stdout


def test_pack_script_and_restore_script(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "secrets.yaml").write_text("password: do-not-log\n", encoding="utf-8")
    (config / "home-assistant_v2.db").write_bytes(b"db-contents")
    archive = tmp_path / "ha-backup.tar.gz"
    env = os.environ.copy()
    env["HA_CONFIG"] = str(config)
    env["HA_ARCHIVE"] = str(archive)
    packed = subprocess.run(  # noqa: S603
        [sys.executable, str(PACK)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert packed.returncode == 0, packed.stderr
    assert "do-not-log" not in packed.stdout
    assert "do-not-log" not in packed.stderr

    restore_dir = tmp_path / "restored"
    restore_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    aws = fake_bin / "aws"
    digest = hashlib.sha256(archive.read_bytes()).digest()
    checksum = base64.b64encode(digest).decode("ascii")
    size = archive.stat().st_size
    aws.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                'if [ "$1" = "s3api" ] && [ "$2" = "get-object" ]; then',
                '  dest=""',
                '  for arg in "$@"; do dest=$arg; done',
                '  cp "$HA_FIXTURE" "$dest"',
                "  exit 0",
                "fi",
                'if [ "$1" = "s3api" ] && [ "$2" = "head-object" ]; then',
                '  case "$*" in',
                "    *ServerSideEncryption*) printf aws:kms ;;",
                f"    *ContentLength*) printf {size} ;;",
                f"    *ChecksumSHA256*) printf {checksum} ;;",
                "  esac",
                "  exit 0",
                "fi",
                "echo unexpected >&2",
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    run_env = os.environ.copy()
    run_env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + run_env.get("PATH", ""),
            "HA_CONFIG": str(restore_dir),
            "HA_ARCHIVE": str(tmp_path / "downloaded.tar.gz"),
            "HA_NAMES": str(tmp_path / "names.txt"),
            "HA_BUCKET": "grow-room-telemetry-590183769702",
            "HA_KEY": "ha-backups/20261103T120000Z.tar.gz",
            "HA_FIXTURE": str(archive),
        }
    )
    bash = shutil.which("bash")
    assert bash
    restored = subprocess.run(  # noqa: S603
        [bash, str(RESTORE)],
        check=False,
        capture_output=True,
        text=True,
        env=run_env,
    )
    assert restored.returncode == 0, restored.stderr
    assert "do-not-log" not in restored.stdout
    assert "do-not-log" not in restored.stderr
    assert (restore_dir / "home-assistant_v2.db").read_bytes() == b"db-contents"
    assert json.loads(restored.stdout)["skipped"] is False

    again = subprocess.run(  # noqa: S603
        [bash, str(RESTORE)],
        check=False,
        capture_output=True,
        text=True,
        env=run_env,
    )
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["skipped"] is True


def _powershell_function(text: str, name: str) -> str:
    return text.split(f"function {name}", 1)[1].split("\nfunction ", 1)[0]


def test_wsl_listing_uses_the_first_name_and_accepts_utf16():
    ha = load()
    utf16 = "Ubuntu\r\ndocker-desktop\r\n".encode("utf-16-le")
    assert ha.wsl_default_distro(utf16) == "Ubuntu"
    bom = "\ufeffUbuntu\n".encode("utf-16-le")
    assert ha.wsl_default_distro(bom) == "Ubuntu"
    marked = b"* Ubuntu (Default)\ndocker-desktop\n"
    assert ha.wsl_default_distro(marked) == "Ubuntu"
    skipped = b"not a distro\nUbuntu\n"
    assert ha.wsl_default_distro(skipped) == "Ubuntu"
    with pytest.raises(ValueError):
        ha.wsl_default_distro(b"")


def test_map_config_path_wsl_unc_drive_and_desktop_mounts():
    ha = load()
    linux = "/home/colem/src/grow-room-platform/ha-config"
    assert ha.map_config_path(linux, "Ubuntu") == (
        r"\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config"
    )
    assert ha.map_config_path("/", "Ubuntu") == r"\\wsl.localhost\Ubuntu"
    desktop = "/run/desktop/mnt/host/c/src/grow-room-platform/ha-config"
    assert ha.map_config_path(desktop, "") == r"C:\src\grow-room-platform\ha-config"
    assert ha.map_config_path("/mnt/c/src/grow-room-platform/ha-config", "") == (
        r"C:\src\grow-room-platform\ha-config"
    )
    unc = r"\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config"
    assert ha.map_config_path(unc, "") == unc
    assert ha.map_config_path(r"C:\src\grow-room-platform\ha-config", "") == (
        r"C:\src\grow-room-platform\ha-config"
    )
    assert ha.needs_wsl_distro(linux) is True
    assert ha.needs_wsl_distro(desktop) is False
    assert ha.needs_wsl_distro("/mnt/c/src") is False
    with pytest.raises(ValueError):
        ha.map_config_path("/home/colem/../../etc", "Ubuntu")
    with pytest.raises(ValueError):
        ha.map_config_path(linux, "Ubuntu;rm")
    with pytest.raises(ValueError):
        ha.map_config_path(linux, "")


def test_resolve_config_path_prefers_explicit_then_mount_then_repo():
    ha = load()
    repo = r"C:\src\grow-room-platform\ha-config"
    mount = "/home/colem/src/grow-room-platform/ha-config"
    explicit = ha.resolve_config_path(
        {
            "explicit": r"D:\ha-config",
            "mount_source": mount,
            "distro": "Ubuntu",
            "repo_config": repo,
        }
    )
    assert explicit == {"path": r"D:\ha-config", "origin": "explicit", "need_distro": False}
    need = ha.resolve_config_path(
        {"explicit": "", "mount_source": mount, "distro": "", "repo_config": repo}
    )
    assert need["need_distro"] is True
    assert need["origin"] == "container-mount"
    assert need["path"] == ""
    mapped = ha.resolve_config_path(
        {"explicit": "", "mount_source": mount, "distro": "Ubuntu", "repo_config": repo}
    )
    assert mapped["origin"] == "container-mount"
    assert mapped["need_distro"] is False
    assert mapped["path"] == (r"\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config")
    default = ha.resolve_config_path(
        {"explicit": "", "mount_source": "", "distro": "", "repo_config": repo}
    )
    assert default == {"path": repo, "origin": "repo-default", "need_distro": False}
    desktop = ha.resolve_config_path(
        {
            "explicit": "",
            "mount_source": "/run/desktop/mnt/host/c/src/grow-room-platform/ha-config",
            "distro": "",
            "repo_config": repo,
        }
    )
    assert desktop["need_distro"] is False
    assert desktop["path"] == repo


def test_select_home_container_prefers_the_running_compose_service():
    ha = load()
    mount = "/home/colem/src/grow-room-platform/ha-config"
    picked = ha.select_home_container(
        [
            {
                "name": "sensor-service",
                "running": True,
                "service": "sensor-service",
                "source": "/app",
            },
            {
                "name": "other-homeassistant",
                "running": True,
                "service": "",
                "source": "/data/other",
            },
            {
                "name": "/grow-room-platform-homeassistant-1",
                "running": True,
                "service": "homeassistant",
                "source": mount,
            },
        ]
    )
    assert picked["name"] == "grow-room-platform-homeassistant-1"
    assert picked["running"] is True
    assert picked["source"] == mount
    assert picked["service"] == "homeassistant"

    stopped = ha.select_home_container(
        {
            "name": "/grow-room-platform-homeassistant-1",
            "running": "false",
            "service": "homeassistant",
            "source": mount,
        }
    )
    assert stopped["name"] == "grow-room-platform-homeassistant-1"
    assert stopped["running"] is False

    running_name = ha.select_home_container(
        [
            {
                "name": "grow-room-platform-homeassistant-1",
                "running": False,
                "service": "homeassistant",
                "source": "/home/old",
            },
            {
                "name": "other-homeassistant",
                "running": True,
                "service": "",
                "source": mount,
            },
        ]
    )
    assert running_name["name"] == "other-homeassistant"
    assert ha.select_home_container([])["name"] == ""


def test_archive_plan_tars_inside_wsl_and_keeps_drive_paths_on_python():
    ha = load()
    config = r"\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config"
    archive = r"C:\Users\colem\AppData\Local\Temp\ha.tar.gz"
    staged = r"C:\Users\colem\AppData\Local\Temp\ha-stage"
    plan = ha.archive_plan(config, archive, staged)
    assert plan["use_wsl"] is True
    assert plan["distro"] == "Ubuntu"
    assert plan["linux_config"] == "/home/colem/src/grow-room-platform/ha-config"
    assert plan["pack"] == [
        "tar",
        "-C",
        "/home/colem/src/grow-room-platform/ha-config",
        "-czf",
        "/mnt/c/Users/colem/AppData/Local/Temp/ha.tar.gz",
        "--one-file-system",
        "--exclude=*.sock",
        ".",
    ]
    commands = [step["argv"][0] for step in plan["steps"]]
    assert commands.count("bash") == 2
    assert "/usr/bin/test" in commands
    assert "cp" in commands
    rollback = [step for step in plan["steps"] if step["when"] == "rollback"]
    assert len(rollback) == 1
    assert "$1" in rollback[0]["argv"][2]
    copy = next(step for step in plan["steps"] if step["argv"][0] == "cp")
    assert copy["argv"][2].endswith("/.")
    local = ha.archive_plan(r"C:\src\grow-room-platform\ha-config", archive)
    assert local["use_wsl"] is False
    assert local["pack"] == []
    with pytest.raises(ValueError, match="inside"):
        ha.archive_plan(r"\\wsl.localhost\Ubuntu\mnt\c\temp", r"C:\temp\ha.tar.gz")


def test_cli_wsl_distro_and_resolve_config(tmp_path):
    raw = base64.b64encode("Ubuntu\n".encode("utf-16-le")).decode("ascii")
    listed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "wsl-distro", "--base64", raw],
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["distro"] == "Ubuntu"
    payload = tmp_path / "in.json"
    payload.write_text(
        json.dumps(
            {
                "explicit": "",
                "mount_source": "/home/colem/src/grow-room-platform/ha-config",
                "distro": "Ubuntu",
                "repo_config": r"C:\src\grow-room-platform\ha-config",
            }
        ),
        encoding="utf-8",
    )
    resolved = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "resolve-config", "--input", str(payload)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert resolved.returncode == 0, resolved.stderr
    body = json.loads(resolved.stdout)
    assert body["origin"] == "container-mount"
    assert body["path"].endswith(r"\ha-config")
    assert "token" not in resolved.stdout


def test_powershell_resolves_ha_config_path_and_targets_the_container():
    poc = POC.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "[string]$HaConfigPath" in poc
    assert "Get-HaStartHint" in poc
    assert "GROW_HA_CONFIG_PATH" in helper
    assert "GROW_HA_CONFIG_PATH" in example
    assert "wsl.localhost" in helper
    assert "-l -q" in helper
    assert "28591" in helper
    assert "wsl-distro" in helper
    assert "docker inspect" in helper
    assert "com.docker.compose.service" in helper
    explicit = _powershell_function(helper, "Get-ExplicitHaConfigPath")
    assert explicit.index("$HaConfigPath") < explicit.index("$env:GROW_HA_CONFIG_PATH")
    assert explicit.index("$env:GROW_HA_CONFIG_PATH") < explicit.index("Read-DotEnvValue")
    stop = _powershell_function(helper, "Stop-HomeHa")
    start = _powershell_function(helper, "Start-HomeHa")
    assert "docker stop" in stop
    assert "docker start" in start
    for body in (stop, start):
        assert "& docker compose" not in body
        assert "project-directory" not in body
    dry = _powershell_function(helper, "Invoke-HaDryRunChecks")
    assert dry.index("Write-HaLayout") < dry.index("Assert-HaMovePreflight")
    for banned in (
        "Stop-HomeHa",
        "Start-HomeHa",
        "Backup-HomeConfigToS3",
        "Send-VerifiedBackup",
        "Invoke-PackHaConfig",
        "Invoke-WslArgv",
        "docker stop",
        "docker start",
    ):
        assert banned not in dry
    prepare = _powershell_function(helper, "Invoke-WithHaPrepare")
    assert prepare.index("Write-HaLayout") < prepare.index('if ($plan.action -eq "dry-run")')
    assert prepare.index('if ($plan.action -eq "dry-run")') < prepare.index("Stop-HomeHa")
    pack = _powershell_function(helper, "Invoke-PackHaConfig")
    assert "use_wsl" in pack
    assert "check-archive" in pack
    assert '"pack"' in pack
    wsl_cmd = _powershell_function(helper, "Invoke-WslArgv")
    assert "-u root" in wsl_cmd
    assert "-u root" in _powershell_function(helper, "Test-HaDatabaseFile")
    restore = _powershell_function(helper, "Restore-HomeFromS3Key")
    assert "Invoke-StageArchive" in restore
    assert "Invoke-WslRestoreSteps" in restore
    assert "restore-home" in restore
    assert "stage-archive" in _powershell_function(helper, "Invoke-StageArchive")
    layout = _powershell_function(helper, "Resolve-HaLayout")
    assert "config_dir" in layout
    assert "need_distro" in layout
    assert "Get-WslDefaultDistro" in layout


def test_phase8_doc_covers_cost_data_and_failure_modes():
    doc = (ROOT / "docs" / "aws-poc" / "PHASE8_HA_MIGRATION.md").read_text(encoding="utf-8")
    assert "0.70" in doc
    assert "down" in doc
    assert "ha-config" in doc
    assert "home-assistant_v2.db" in doc
    assert "grow-room-telemetry-590183769702" in doc
    assert "alias/grow-room/telemetry" in doc
    assert "SQLite" in doc
    assert "Prometheus" in doc
    assert "Athena" in doc
    assert "one" in doc.lower()
    for phrase in ("backup", "Dry run", "both copies", "KMS"):
        assert phrase in doc or phrase.lower() in doc.lower()
    for phrase in (
        "HaConfigPath",
        "GROW_HA_CONFIG_PATH",
        "wsl.localhost",
        "docker stop",
        "UTF-16",
        "config path",
    ):
        assert phrase in doc
