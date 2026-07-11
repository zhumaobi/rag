from __future__ import annotations

import enum


class PipelineState(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    SWITCHING = "SWITCHING"
    DONE = "DONE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


# Allowed forward transitions; anything else raises.
_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.PENDING: {PipelineState.PROCESSING, PipelineState.FAILED},
    PipelineState.PROCESSING: {PipelineState.VALIDATING, PipelineState.FAILED},
    PipelineState.VALIDATING: {PipelineState.READY, PipelineState.FAILED},
    PipelineState.READY: {PipelineState.SWITCHING, PipelineState.FAILED},
    PipelineState.SWITCHING: {PipelineState.DONE, PipelineState.ROLLED_BACK, PipelineState.FAILED},
    PipelineState.DONE: set(),
    PipelineState.FAILED: {PipelineState.ROLLED_BACK},
    PipelineState.ROLLED_BACK: set(),
}


class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, state: PipelineState = PipelineState.PENDING) -> None:
        self.state = state

    def can(self, target: PipelineState) -> bool:
        return target in _TRANSITIONS[self.state]

    def to(self, target: PipelineState) -> PipelineState:
        if not self.can(target):
            raise InvalidTransition(f"{self.state} -> {target} not allowed")
        self.state = target
        return self.state

    @property
    def is_terminal(self) -> bool:
        return not _TRANSITIONS[self.state]
