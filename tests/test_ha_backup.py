"""The Pi backup script snapshots SQLite and skips an unmounted second copy."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible" / "roles" / "ha_backup" / "files" / "ha-backup"
BASH = "/usr/bin/bash"
FINDMNT = "/usr/bin/findmnt"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    merged.pop("INVOCATION_ID", None)
    return subprocess.run(  # noqa: S603
        [BASH, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=merged,
    )


def _source(path: Path) -> str:
    return subprocess.check_output(  # noqa: S603
        [FINDMNT, "-n", "-o", "SOURCE", "-T", str(path)],
        text=True,
    ).strip()


def _dir_on_root_fs(tmp_path: Path) -> Path:
    root = _source(Path("/"))
    if _source(tmp_path) == root:
        return tmp_path
    home = Path.home()
    if home.is_dir() and _source(home) == root:
        dest = home / f".ha-backup-test-{os.getpid()}"
        dest.mkdir(exist_ok=True)
        return dest
    pytest.skip("no directory on the root filesystem")


def test_script_is_executable_lf_utf8():
    raw = SCRIPT.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    raw.decode("utf-8")
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR


def test_backup_snapshots_sqlite_and_drops_wal(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "configuration.yaml").write_text("default_config:\n", encoding="utf-8")
    (config / "home-assistant_v2.db-wal").write_text("should-not-be-archived\n", encoding="utf-8")
    (config / "home-assistant_v2.db-shm").write_bytes(b"shm")
    db_path = config / "home-assistant_v2.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE sample (note TEXT)")
    connection.execute("INSERT INTO sample (note) VALUES ('sentinel')")
    connection.commit()
    connection.close()

    dest = tmp_path / "backups"
    result = _run(
        {
            "HA_BACKUP_CONFIG": str(config),
            "HA_BACKUP_DEST": str(dest),
            "HA_BACKUP_RETENTION": "14",
            "HA_BACKUP_SECOND_DEST": "",
        }
    )
    assert result.returncode == 0, result.stderr
    archives = list(dest.glob("homeassistant-config-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        names = archive.getnames()
        assert any(name.endswith("configuration.yaml") for name in names)
        assert any(name.endswith("home-assistant_v2.db") for name in names)
        assert not any(name.endswith("home-assistant_v2.db-wal") for name in names)
        assert not any(name.endswith("home-assistant_v2.db-shm") for name in names)
        member = next(name for name in names if name.endswith("home-assistant_v2.db"))
        extracted = archive.extractfile(member)
        assert extracted is not None
        snapshot = tmp_path / "snapshot.db"
        snapshot.write_bytes(extracted.read())
    check = sqlite3.connect(snapshot)
    note = check.execute("SELECT note FROM sample").fetchone()
    check.close()
    assert note == ("sentinel",)
    assert "snapshotted home-assistant_v2.db" in result.stdout


def test_retention_keeps_the_newest(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "configuration.yaml").write_text("ok\n", encoding="utf-8")
    dest = tmp_path / "backups"
    dest.mkdir()
    for index in range(4):
        old = dest / f"homeassistant-config-2000010{index}-000000.tar.gz"
        old.write_bytes(b"old")
        os.utime(old, (1_000_000_000 + index, 1_000_000_000 + index))

    result = _run(
        {
            "HA_BACKUP_CONFIG": str(config),
            "HA_BACKUP_DEST": str(dest),
            "HA_BACKUP_RETENTION": "2",
            "HA_BACKUP_SECOND_DEST": "",
        }
    )
    assert result.returncode == 0, result.stderr
    kept = sorted(path.name for path in dest.glob("homeassistant-config-*.tar.gz"))
    assert len(kept) == 2
    assert [name for name in kept if not name.startswith("homeassistant-config-2000")]
    assert "homeassistant-config-20000103-000000.tar.gz" in kept
    for index in range(3):
        assert f"homeassistant-config-2000010{index}-000000.tar.gz" not in kept


def test_second_destination_on_the_root_filesystem_is_skipped(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "configuration.yaml").write_text("ok\n", encoding="utf-8")
    dest = tmp_path / "backups"
    second_root = _dir_on_root_fs(tmp_path)
    second = second_root / "second"
    try:
        result = _run(
            {
                "HA_BACKUP_CONFIG": str(config),
                "HA_BACKUP_DEST": str(dest),
                "HA_BACKUP_RETENTION": "14",
                "HA_BACKUP_SECOND_DEST": str(second),
            }
        )
        assert result.returncode == 0, result.stderr
        assert "not mounted on its own filesystem; skipping" in result.stdout
        assert not second.exists()
    finally:
        if second_root != tmp_path:
            shutil.rmtree(second_root, ignore_errors=True)


def test_missing_config_and_bad_retention_fail(tmp_path: Path):
    missing = _run(
        {
            "HA_BACKUP_CONFIG": str(tmp_path / "missing"),
            "HA_BACKUP_DEST": str(tmp_path / "backups"),
            "HA_BACKUP_RETENTION": "14",
            "HA_BACKUP_SECOND_DEST": "",
        }
    )
    assert missing.returncode != 0
    bad = _run(
        {
            "HA_BACKUP_CONFIG": str(tmp_path),
            "HA_BACKUP_DEST": str(tmp_path / "backups"),
            "HA_BACKUP_RETENTION": "fourteen",
            "HA_BACKUP_SECOND_DEST": "",
        }
    )
    assert bad.returncode != 0
