"""Safety-supervisor action boundary used by the episode logger."""

from dataclasses import dataclass
from typing import Mapping

from av_safeplan.policies.base import PolicyObservation, VehicleControlCommand


@dataclass(frozen=True)
class SupervisorDecision:
    action: VehicleControlCommand
    intervened: bool
    reason: str


class PassthroughSupervisor:
    """Baseline supervisor that records the action boundary without intervention."""

    name = "passthrough"

    def supervise(
        self,
        observation: PolicyObservation,
        base_action: VehicleControlCommand,
        signals: Mapping[str, float],
    ) -> SupervisorDecision:
        del observation, signals
        return SupervisorDecision(
            action=base_action,
            intervened=False,
            reason="passthrough",
        )
