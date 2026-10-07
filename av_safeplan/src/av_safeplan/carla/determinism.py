"""Deterministic CARLA seeding, route planning, and run manifests."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class RoutePlan:
    """Stable spawn-point indices identifying one replayable route."""

    map_name: str
    spawn_index: int
    destination_index: int

    @property
    def route_id(self) -> str:
        return "{}:spawn-{:03d}:destination-{:03d}".format(
            self.map_name,
            self.spawn_index,
            self.destination_index,
        )


def apply_deterministic_seeds(world: Any, traffic_manager: Any, seed: int) -> None:
    """Seed Python and CARLA-owned random generators used by a route run."""
    random.seed(seed)
    traffic_manager.set_random_device_seed(seed)
    if hasattr(world, "set_pedestrians_seed"):
        world.set_pedestrians_seed(seed)


def select_route_plan(
    map_name: str,
    spawn_points: Sequence[Any],
    seed: int,
    spawn_index: Optional[int] = None,
    destination_index: Optional[int] = None,
) -> RoutePlan:
    """Select a stable route from explicit indices or a deterministic seed."""
    if len(spawn_points) < 2:
        raise RuntimeError("Town does not provide enough spawn points")

    if spawn_index is None:
        candidates = list(range(len(spawn_points)))
        random.Random(seed).shuffle(candidates)
        selected_spawn = candidates[0]
    else:
        selected_spawn = _validated_index("spawn", spawn_index, len(spawn_points))

    if destination_index is None:
        origin = spawn_points[selected_spawn].location
        destination_candidates = [
            index for index in range(len(spawn_points)) if index != selected_spawn
        ]
        selected_destination = max(
            destination_candidates,
            key=lambda index: (
                origin.distance(spawn_points[index].location),
                -index,
            ),
        )
    else:
        selected_destination = _validated_index(
            "destination",
            destination_index,
            len(spawn_points),
        )

    if selected_spawn == selected_destination:
        raise ValueError("Spawn and destination indices must be different")

    return RoutePlan(
        map_name=map_name,
        spawn_index=selected_spawn,
        destination_index=selected_destination,
    )


def route_manifest(route: RoutePlan, spawn_points: Sequence[Any]) -> Dict[str, Any]:
    """Serialize a route and its endpoint transforms for later replay audits."""
    return {
        "route_id": route.route_id,
        "map": route.map_name,
        "spawn_index": route.spawn_index,
        "destination_index": route.destination_index,
        "spawn_transform": _transform_manifest(spawn_points[route.spawn_index]),
        "destination_transform": _transform_manifest(
            spawn_points[route.destination_index]
        ),
    }


def build_run_manifest(
    *,
    project: str,
    seed: int,
    route: Mapping[str, Any],
    fixed_delta_seconds: float,
    requested_steps: int,
    policy: str,
    behavior: str,
    carla_client_version: str,
    carla_server_version: str,
    recording: Mapping[str, Any],
) -> Dict[str, Any]:
    """Create the immutable configuration section of a CARLA run manifest."""
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "mode": "carla_closed_loop",
        "seed": int(seed),
        "route": dict(route),
        "simulation": {
            "synchronous_mode": True,
            "fixed_delta_seconds": float(fixed_delta_seconds),
            "requested_steps": int(requested_steps),
        },
        "policy": {
            "name": policy,
            "behavior": behavior,
        },
        "carla": {
            "client_version": carla_client_version,
            "server_version": carla_server_version,
        },
        "recording": dict(recording),
        "outcome": {
            "status": "running",
            "executed_steps": 0,
            "destination_reached": False,
        },
    }


def write_run_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write a manifest atomically so interrupted runs retain valid JSON."""
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _validated_index(label: str, index: int, count: int) -> int:
    if index < 0 or index >= count:
        raise ValueError(
            "{} index {} is outside the available range 0..{}".format(
                label.capitalize(),
                index,
                count - 1,
            )
        )
    return index


def _transform_manifest(transform: Any) -> Dict[str, Dict[str, float]]:
    return {
        "location": {
            axis: float(getattr(transform.location, axis))
            for axis in ("x", "y", "z")
        },
        "rotation": {
            axis: float(getattr(transform.rotation, axis))
            for axis in ("pitch", "yaw", "roll")
        },
    }
