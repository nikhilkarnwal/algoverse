"""CARLA Behavior Agent adapter for the common policy interface."""

from typing import Any, Optional

from av_safeplan.policies.base import BasePolicy, PolicyObservation, VehicleControlCommand


class BehaviorAgentPolicy(BasePolicy):
    name = "behavior_agent"

    def __init__(
        self,
        actor: Any,
        destination: Any,
        behavior: str = "normal",
        target_speed_mps: Optional[float] = None,
    ):
        from agents.navigation.behavior_agent import BehaviorAgent

        self._agent = BehaviorAgent(actor, behavior=behavior)
        self._agent.set_destination(destination)
        if target_speed_mps is not None:
            if target_speed_mps <= 0:
                raise ValueError("target_speed_mps must be positive")
            self._agent.set_target_speed(float(target_speed_mps) * 3.6)

    def act(self, observation: PolicyObservation) -> VehicleControlCommand:
        del observation
        return VehicleControlCommand.from_carla(self._agent.run_step())

    def done(self) -> bool:
        return bool(self._agent.done())
