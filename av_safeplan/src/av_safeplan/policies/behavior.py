"""CARLA Behavior Agent adapter for the common policy interface."""

from typing import Any, Optional, Sequence, Tuple

from av_safeplan.policies.base import BasePolicy, PolicyObservation, VehicleControlCommand


class BehaviorAgentPolicy(BasePolicy):
    name = "behavior_agent"

    def __init__(
        self,
        actor: Any,
        destination: Optional[Any] = None,
        behavior: str = "normal",
        target_speed_mps: Optional[float] = None,
        global_plan: Optional[Sequence[Tuple[Any, Any]]] = None,
    ):
        from agents.navigation.behavior_agent import BehaviorAgent

        self._agent = BehaviorAgent(actor, behavior=behavior)
        if global_plan:
            self._agent.set_global_plan(list(global_plan))
        elif destination is not None:
            self._agent.set_destination(destination)
        else:
            raise ValueError("destination or global_plan is required")
        if target_speed_mps is not None:
            if target_speed_mps <= 0:
                raise ValueError("target_speed_mps must be positive")
            self._agent.set_target_speed(float(target_speed_mps) * 3.6)

    def act(self, observation: PolicyObservation) -> VehicleControlCommand:
        del observation
        if self._agent.done():
            return VehicleControlCommand(steer=0.0, throttle=0.0, brake=1.0)
        return VehicleControlCommand.from_carla(self._agent.run_step())

    def done(self) -> bool:
        return bool(self._agent.done())
