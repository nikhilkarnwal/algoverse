"""Lazy adapter around SimLingo's official CARLA Leaderboard agent."""

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from av_safeplan.policies.base import BasePolicy, PolicyObservation, VehicleControlCommand


class SimLingoPolicy(BasePolicy):
    """Expose the frozen upstream LingoAgent through the shared policy API.

    SimLingo retains its official Leaderboard sensor dictionary and global-plan
    contract. Heavy CUDA/model imports happen only when this adapter is created.
    """

    name = "simlingo"

    def __init__(
        self,
        checkpoint: Path,
        global_plan_gps: Sequence[Any],
        global_plan_world: Sequence[Any],
        *,
        host: str = "127.0.0.1",
        port: int = 2000,
        debug: int = 0,
        route_index: Optional[str] = None,
    ):
        if not checkpoint.is_file():
            raise FileNotFoundError("SimLingo checkpoint not found: {}".format(checkpoint))

        from team_code.agent_simlingo import LingoAgent

        self._agent = LingoAgent(host, port, debug)
        self._agent.set_global_plan(list(global_plan_gps), list(global_plan_world))
        self._agent.setup(str(checkpoint), route_index=route_index)

    def sensor_specifications(self) -> Sequence[Mapping[str, Any]]:
        return self._agent.sensors()

    def act(self, observation: PolicyObservation) -> VehicleControlCommand:
        if not observation.sensors:
            raise ValueError(
                "SimLingo requires the official Leaderboard sensor dictionary"
            )
        control = self._agent.run_step(
            dict(observation.sensors),
            timestamp=observation.timestamp_seconds,
        )
        return VehicleControlCommand.from_carla(control)

    def close(self) -> None:
        if self._agent is not None:
            self._agent.destroy()
            self._agent = None
