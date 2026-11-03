"""Helm render of the alert toggles. Skips when the helm binary is absent."""

import os
import shutil
import subprocess

import pytest

from tests.check_grow_alert_toggles import check, helm_bin


def test_each_alert_toggle_renders_on_and_off():
    binary = helm_bin()
    if (
        shutil.which(binary) is None
        and subprocess.run([binary, "version"], capture_output=True).returncode != 0  # noqa: S603
    ):
        if os.environ.get("REQUIRE_HELM") == "1":
            raise AssertionError(f"{binary} is required")
        pytest.skip("helm not installed")
    check()
