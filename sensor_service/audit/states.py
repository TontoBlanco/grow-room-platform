"""Allowed plant state transitions (finite state machine).

Think of this like a ValidatingAdmissionWebhook for plant lifecycle:
illegal edges are rejected before they ever hit the append-only log.
"""

from __future__ import annotations

from sensor_service.audit.models import PlantState

# Forward-only grow path, plus destroy (cull) from any live stage.
ALLOWED_TRANSITIONS: dict[PlantState, frozenset[PlantState]] = {
    PlantState.SEEDLING: frozenset({PlantState.VEGETATIVE, PlantState.DESTROYED}),
    PlantState.VEGETATIVE: frozenset({PlantState.FLOWERING, PlantState.DESTROYED}),
    PlantState.FLOWERING: frozenset({PlantState.HARVESTED, PlantState.DESTROYED}),
    PlantState.HARVESTED: frozenset({PlantState.PACKAGED, PlantState.DESTROYED}),
    PlantState.PACKAGED: frozenset({PlantState.DESTROYED}),
    PlantState.DESTROYED: frozenset(),  # terminal
}


def can_transition(from_state: PlantState, to_state: PlantState) -> bool:
    if from_state == to_state:
        return False
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def describe_allowed(from_state: PlantState) -> list[str]:
    return sorted(s.value for s in ALLOWED_TRANSITIONS.get(from_state, frozenset()))
