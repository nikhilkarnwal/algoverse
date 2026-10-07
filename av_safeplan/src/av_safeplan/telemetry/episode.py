"""Shared JSONL logger for policy, scenario, and safety supervision runs."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from av_safeplan.policies.base import PolicyObservation, VehicleControlCommand


class EpisodeLogger:
    """Append one complete, serializable record per simulation step."""

    def __init__(
        self,
        path: Path,
        *,
        seed: int,
        route: Mapping[str, Any],
        policy_name: str,
        scenario: Optional[Mapping[str, Any]] = None,
    ):
        self.path = path
        self.path.touch(exist_ok=False)
        self._context = {
            "seed": int(seed),
            "route": dict(route),
            "policy": policy_name,
            "scenario": dict(scenario or {}),
        }
        self.records_written = 0

    def append(
        self,
        observation: PolicyObservation,
        base_policy_action: VehicleControlCommand,
        safety_supervisor_action: VehicleControlCommand,
        events: Iterable[Mapping[str, Any]],
        *,
        supervisor_intervened: bool = False,
    ) -> None:
        record: Dict[str, Any] = {
            "frame": observation.frame,
            "timestamp_seconds": observation.timestamp_seconds,
            "ego": dict(observation.ego),
            "nearby_actors": dict(observation.nearby_actors),
            "traffic_lights": dict(observation.traffic_lights),
            "route_state": dict(observation.route),
            "base_policy_action": base_policy_action.to_dict(),
            "safety_supervisor_action": safety_supervisor_action.to_dict(),
            "supervisor_intervened": bool(supervisor_intervened),
            "events": [dict(event) for event in events],
            **self._context,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        self.records_written += 1
