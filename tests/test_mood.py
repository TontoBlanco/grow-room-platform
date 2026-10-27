"""Leaf-VPD mood bands. Boundaries are the contract, not the constant names."""

import pytest

from sensor_service.mood import HEURISTIC_NOTE, mood_for_vpd


@pytest.mark.parametrize(
    ("vpd_kpa", "band", "mood", "score", "emoji"),
    [
        (0.0, "stressful_humid", "swampy", 1, "🫠"),
        (-0.1, "stressful_humid", "swampy", 1, "🫠"),
        (0.399, "stressful_humid", "swampy", 1, "🫠"),
        (0.4, "muggy", "muggy", 2, "💧"),
        (0.799, "muggy", "muggy", 2, "💧"),
        (0.8, "ideal", "cozy", 3, "🌿"),
        (1.0, "ideal", "cozy", 3, "🌿"),
        (1.2, "ideal", "cozy", 3, "🌿"),
        (1.201, "too_dry", "thirsty", 4, "💨"),
        (1.6, "too_dry", "thirsty", 4, "💨"),
        (1.601, "stressful_dry", "crispy", 5, "🥵"),
        (2.4, "stressful_dry", "crispy", 5, "🥵"),
    ],
)
def test_vpd_band_thresholds(vpd_kpa, band, mood, score, emoji):
    current = mood_for_vpd(vpd_kpa)
    assert current.band == band
    assert current.mood == mood
    assert current.score == score
    assert current.emoji == emoji
    assert current.message


def test_ideal_payload_matches_the_cozy_shape():
    payload = mood_for_vpd(1.0).to_dict(vpd_kpa=1.0)
    assert payload == {
        "mood": "cozy",
        "emoji": "🌿",
        "vpd_kpa": 1.0,
        "message": "Sweet spot — stomata are vibing",
        "band": "ideal",
        "score": 3,
        "note": HEURISTIC_NOTE,
    }
    assert "agronomy" in payload["note"].lower()
    assert "heuristic" in payload["note"].lower()


def test_payload_includes_climate_when_the_caller_has_it():
    payload = mood_for_vpd(0.5).to_dict(
        vpd_kpa=0.5,
        temperature_c=24.0,
        humidity_percent=80.0,
    )
    assert payload["band"] == "muggy"
    assert payload["temperature_c"] == 24.0
    assert payload["humidity_percent"] == 80.0
    assert payload["score"] == 2
