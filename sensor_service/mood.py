"""Playful plant-mood bands from leaf VPD.

These are soft UX heuristics for a mixed tent, not agronomy advice and not
stage-specific targets. Seedlings often want a lower VPD than late flower.
The score is a dry-direction category code for charts (higher means drier),
not a quality ranking.
"""

from dataclasses import dataclass

# Leaf VPD edges in kPa. Ideal includes both 0.8 and 1.2.
HUMID_STRESS_BELOW = 0.4
MUGGY_BELOW = 0.8
IDEAL_MAX = 1.2
TOO_DRY_MAX = 1.6

HEURISTIC_NOTE = (
    "Soft heuristic for a mixed tent. Not agronomy advice, "
    "not a stage-specific target, and not a control signal."
)


@dataclass(frozen=True)
class PlantMood:
    """One mood band. `score` is the value exported on the active Prometheus series."""

    band: str
    mood: str
    emoji: str
    message: str
    score: int

    def to_dict(
        self,
        *,
        vpd_kpa: float,
        temperature_c: float | None = None,
        humidity_percent: float | None = None,
    ) -> dict:
        payload = {
            "mood": self.mood,
            "emoji": self.emoji,
            "vpd_kpa": vpd_kpa,
            "message": self.message,
            "band": self.band,
            "score": self.score,
            "note": HEURISTIC_NOTE,
        }
        if temperature_c is not None:
            payload["temperature_c"] = temperature_c
        if humidity_percent is not None:
            payload["humidity_percent"] = humidity_percent
        return payload


STRESSFUL_HUMID = PlantMood(
    band="stressful_humid",
    mood="swampy",
    emoji="🫠",
    message="Air is soup. Give the breeze a turn before the canopy sulks.",
    score=1,
)
MUGGY = PlantMood(
    band="muggy",
    mood="muggy",
    emoji="💧",
    message="A little close in here. Clones would sign off; flower might want it drier.",
    score=2,
)
IDEAL = PlantMood(
    band="ideal",
    mood="cozy",
    emoji="🌿",
    message="Sweet spot — stomata are vibing",
    score=3,
)
TOO_DRY = PlantMood(
    band="too_dry",
    mood="thirsty",
    emoji="💨",
    message="Flower-range dry. Lovely if you meant it; thirsty if you didn't.",
    score=4,
)
STRESSFUL_DRY = PlantMood(
    band="stressful_dry",
    mood="crispy",
    emoji="🥵",
    message="VPD is running hot. Leaves pull hard before they crisp.",
    score=5,
)

# Publication order for the gauge. Every band is set on each sample so a
# previous band does not stay at its old score.
BANDS: tuple[PlantMood, ...] = (
    STRESSFUL_HUMID,
    MUGGY,
    IDEAL,
    TOO_DRY,
    STRESSFUL_DRY,
)


def mood_for_vpd(vpd_kpa: float) -> PlantMood:
    """Map leaf VPD in kPa to a plant mood.

    Below 0.4 and above 1.6 are both stressful, with different bands, because
    soup and crispy are not the same problem. 0.8 through 1.2 inclusive is
    the cozy middle.
    """
    if vpd_kpa < HUMID_STRESS_BELOW:
        return STRESSFUL_HUMID
    if vpd_kpa < MUGGY_BELOW:
        return MUGGY
    if vpd_kpa <= IDEAL_MAX:
        return IDEAL
    if vpd_kpa <= TOO_DRY_MAX:
        return TOO_DRY
    return STRESSFUL_DRY
