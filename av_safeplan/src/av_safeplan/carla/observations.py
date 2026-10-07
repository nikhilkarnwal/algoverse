"""Serializable policy observations collected from a live CARLA world."""

import math
from typing import Any, Dict, List, Optional

from av_safeplan.policies.base import PolicyObservation


def vector_to_dict(vector: Any) -> Dict[str, float]:
    return {axis: float(getattr(vector, axis)) for axis in ("x", "y", "z")}


def rotation_to_dict(rotation: Any) -> Dict[str, float]:
    return {
        axis: float(getattr(rotation, axis))
        for axis in ("pitch", "yaw", "roll")
    }


def actor_state(actor: Any, ego_location: Optional[Any] = None) -> Dict[str, Any]:
    transform = actor.get_transform()
    velocity = actor.get_velocity()
    state = {
        "id": int(actor.id),
        "type_id": str(actor.type_id),
        "location": vector_to_dict(transform.location),
        "rotation": rotation_to_dict(transform.rotation),
        "velocity": vector_to_dict(velocity),
        "speed_mps": math.sqrt(
            velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z
        ),
    }
    if ego_location is not None:
        state["distance_m"] = float(transform.location.distance(ego_location))
    return state


def collect_observation(
    world: Any,
    ego_vehicle: Any,
    frame: int,
    timestamp_seconds: float,
    *,
    destination: Optional[Any] = None,
    radius_m: float = 50.0,
    route_id: Optional[str] = None,
    sensors: Optional[Dict[str, Any]] = None,
) -> PolicyObservation:
    """Collect the common state required by policy, logger, and labels."""
    ego_transform = ego_vehicle.get_transform()
    ego_location = ego_transform.location
    nearby: List[Dict[str, Any]] = []
    traffic_lights: List[Dict[str, Any]] = []

    for actor in world.get_actors():
        if actor.id == ego_vehicle.id:
            continue
        if not (
            actor.type_id.startswith("vehicle.")
            or actor.type_id.startswith("walker.pedestrian.")
        ):
            continue
        distance = actor.get_location().distance(ego_location)
        if distance <= radius_m:
            nearby.append(actor_state(actor, ego_location))

    for light in world.get_actors().filter("traffic.traffic_light*"):
        distance = light.get_location().distance(ego_location)
        if distance > radius_m:
            continue
        traffic_lights.append({
            "id": int(light.id),
            "state": str(light.state),
            "distance_m": float(distance),
            "location": vector_to_dict(light.get_location()),
        })

    route: Dict[str, Any] = {"route_id": route_id}
    if destination is not None:
        route["destination"] = vector_to_dict(destination)
        route["distance_to_destination_m"] = float(
            ego_location.distance(destination)
        )

    return PolicyObservation(
        frame=int(frame),
        timestamp_seconds=float(timestamp_seconds),
        ego=actor_state(ego_vehicle),
        nearby_actors={"items": nearby, "radius_m": float(radius_m)},
        traffic_lights={"items": traffic_lights, "radius_m": float(radius_m)},
        route=route,
        sensors=sensors or {},
    )
