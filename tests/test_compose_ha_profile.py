"""The PC Compose file must not start Home Assistant by default."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
EXAMPLE = ROOT / ".env.example"


def test_homeassistant_is_opt_in_and_points_at_the_pi():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "profiles:" in text
    assert "local-ha" in text
    assert not any(line.strip().startswith("depends_on:") for line in text.splitlines())
    assert "${HA_URL:-http://10.0.0.62:8123}" in text
    assert "./ha-config:/config" in text
    assert "http://homeassistant:8123}" not in text

    example = EXAMPLE.read_text(encoding="utf-8")
    assert "HA_URL=http://10.0.0.62:8123" in example
    assert "HA_URL=http://homeassistant:8123" not in example.split("Rollback", 1)[0]


def test_compose_and_example_are_lf_utf8():
    for path in (COMPOSE, EXAMPLE):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path.name
        assert b"\r\n" not in raw, path.name
        raw.decode("utf-8")
