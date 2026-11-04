"""Pack /config into one gzip tarball. Used inside the EKS Home Assistant pod.

Prints byte and file counts only. Does not print names or file bytes.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
from pathlib import Path

DB_NAME = "home-assistant_v2.db"


def pack(root: Path, dest: Path) -> dict:
    db = root / DB_NAME
    if not db.is_file() or db.stat().st_size <= 0:
        sys.stderr.write(f"backup refused: {DB_NAME} is not in the config folder\n")
        raise SystemExit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            count += 1
    return {"files": count, "bytes": dest.stat().st_size}


def main() -> int:
    root = Path(os.environ.get("HA_CONFIG", "/config"))
    # The pod's writable scratch dir. The orchestrator sets HA_ARCHIVE in tests.
    dest = Path(os.environ.get("HA_ARCHIVE", "/tmp/ha-backup.tar.gz"))  # noqa: S108
    sys.stdout.write(json.dumps(pack(root, dest)))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
