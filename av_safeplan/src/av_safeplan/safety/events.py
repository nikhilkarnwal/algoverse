"""Collision, red-light, and near-miss event labeling for CARLA episodes."""

from dataclasses import asdict, dataclass
import math
from queue import Empty, Queue
from typing import Any, Dict, List, Mapping, Optional, Tuple

from av_safeplan.policies.base import PolicyObservation


@dataclass(frozen=True)
class SafetyEvent:
    event_type: str
    frame: int
    details: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CollisionMonitor:
    """Attach a collision sensor and expose frame-aligned event labels."""

    def __init__(self, world: Any, ego_vehicle: Any):
        self.world = world
        self.ego_vehicle = ego_vehicle
        self._queue = Queue()
        self._sensor = None

    def start(self) -> None:
        import carla

        blueprint = self.world.get_blueprint_library().find("sensor.other.collision")
        self._sensor = self.world.spawn_actor(
            blueprint,
            carla.Transform(),
            attach_to=self.ego_vehicle,
        )
        self._sensor.listen(self._queue.put)

    def drain(self, through_frame: int) -> List[SafetyEvent]:
        events: List[SafetyEvent] = []
        deferred = []
        while True:
            try:
                collision = self._queue.get_nowait()
            except Empty:
                break
            if collision.frame > through_frame:
                deferred.append(collision)
                continue
            impulse = collision.normal_impulse
            intensity = math.sqrt(
                impulse.x * impulse.x
                + impulse.y * impulse.y
                + impulse.z * impulse.z
            )
            events.append(SafetyEvent(
                event_type="collision",
                frame=int(collision.frame),
                details={
                    "other_actor_id": int(collision.other_actor.id),
                    "other_actor_type": str(collision.other_actor.type_id),
                    "impulse": {
                        "x": float(impulse.x),
                        "y": float(impulse.y),
                        "z": float(impulse.z),
                    },
                    "intensity": float(intensity),
                },
            ))
        for collision in deferred:
            self._queue.put(collision)
        return events

    def close(self) -> None:
        sensor = self._sensor
        self._sensor = None
        if sensor is None:
            return
        try:
            sensor.stop()
        finally:
            if sensor.is_alive:
                sensor.destroy()


class RedLightMonitor:
    """Label a violation when an ego vehicle enters and clears a red signal."""

    def __init__(self, moving_threshold_mps: float = 0.5, stop_threshold_mps: float = 0.15):
        self.moving_threshold_mps = moving_threshold_mps
        self.stop_threshold_mps = stop_threshold_mps
        self._active_light_id: Optional[int] = None
        self._active_light = None
        self._entry_frame: Optional[int] = None
        self._minimum_speed = float("inf")
        self._encroachment_emitted = False

    def update(self, ego_vehicle: Any, observation: PolicyObservation) -> List[SafetyEvent]:
        import carla

        events: List[SafetyEvent] = []
        speed = float(observation.ego.get("speed_mps", 0.0))
        at_light = bool(ego_vehicle.is_at_traffic_light())
        light = ego_vehicle.get_traffic_light() if at_light else None
        light_is_red = light is not None and light.state == carla.TrafficLightState.Red

        if light_is_red:
            light_id = int(light.id)
            if self._active_light_id != light_id:
                self._active_light_id = light_id
                self._active_light = light
                self._entry_frame = observation.frame
                self._minimum_speed = speed
                self._encroachment_emitted = False
            self._minimum_speed = min(self._minimum_speed, speed)
            if speed >= self.moving_threshold_mps and not self._encroachment_emitted:
                events.append(SafetyEvent(
                    # Entering the light's trigger volume while slowing is
                    # not a violation or a near miss by itself.
                    event_type="red_light_trigger_entry",
                    frame=observation.frame,
                    details={"traffic_light_id": light_id, "speed_mps": speed},
                ))
                self._encroachment_emitted = True
            return events

        if self._active_light_id is not None and at_light:
            self._active_light_id = None
            self._active_light = None
            self._entry_frame = None
            self._minimum_speed = float("inf")
            self._encroachment_emitted = False
            return events

        if self._active_light_id is not None:
            if self._active_light.state == carla.TrafficLightState.Red:
                events.append(SafetyEvent(
                    event_type="red_light_violation",
                    frame=observation.frame,
                    details={
                        "traffic_light_id": self._active_light_id,
                        "entry_frame": self._entry_frame,
                        "minimum_speed_mps": self._minimum_speed,
                        "stopped_before_crossing": (
                            self._minimum_speed <= self.stop_threshold_mps
                        ),
                    },
                ))
            self._active_light_id = None
            self._active_light = None
            self._entry_frame = None
            self._minimum_speed = float("inf")
            self._encroachment_emitted = False
        return events


class NearMissMonitor:
    """Label low time-to-collision encounters without claiming a collision."""

    def __init__(
        self,
        max_ttc_seconds: float = 3.0,
        max_closest_distance_m: float = 2.5,
        cooldown_frames: int = 20,
    ):
        self.max_ttc_seconds = max_ttc_seconds
        self.max_closest_distance_m = max_closest_distance_m
        self.cooldown_frames = cooldown_frames
        self._last_event_frame: Dict[int, int] = {}

    def update(self, observation: PolicyObservation) -> List[SafetyEvent]:
        events: List[SafetyEvent] = []
        ego = observation.ego
        ego_location = ego["location"]
        ego_velocity = ego["velocity"]
        actor_items = observation.nearby_actors.get("items", [])
        for actor in actor_items:
            actor_id = int(actor["id"])
            last_frame = self._last_event_frame.get(actor_id, -self.cooldown_frames)
            if observation.frame - last_frame < self.cooldown_frames:
                continue
            ttc, closest_distance = _time_to_closest_approach(
                ego_location,
                ego_velocity,
                actor["location"],
                actor["velocity"],
            )
            if (
                0.0 < ttc <= self.max_ttc_seconds
                and closest_distance <= self.max_closest_distance_m
            ):
                events.append(SafetyEvent(
                    event_type="near_miss",
                    frame=observation.frame,
                    details={
                        "other_actor_id": actor_id,
                        "other_actor_type": actor["type_id"],
                        "ttc_seconds": ttc,
                        "closest_distance_m": closest_distance,
                    },
                ))
                self._last_event_frame[actor_id] = observation.frame
        return events


class SafetyEventMonitor:
    """Combine all Week 1 safety labels behind one lifecycle."""

    def __init__(self, world: Any, ego_vehicle: Any):
        self.collision = CollisionMonitor(world, ego_vehicle)
        self.red_light = RedLightMonitor()
        self.near_miss = NearMissMonitor()
        self.ego_vehicle = ego_vehicle

    def start(self) -> None:
        self.collision.start()

    def update(self, observation: PolicyObservation) -> List[Dict[str, Any]]:
        events = self.collision.drain(observation.frame)
        events.extend(self.red_light.update(self.ego_vehicle, observation))
        events.extend(self.near_miss.update(observation))
        return [event.to_dict() for event in events]

    def close(self) -> None:
        self.collision.close()


def _time_to_closest_approach(
    ego_location: Mapping[str, float],
    ego_velocity: Mapping[str, float],
    actor_location: Mapping[str, float],
    actor_velocity: Mapping[str, float],
) -> Tuple[float, float]:
    relative_position = [
        float(actor_location[axis]) - float(ego_location[axis])
        for axis in ("x", "y", "z")
    ]
    relative_velocity = [
        float(actor_velocity[axis]) - float(ego_velocity[axis])
        for axis in ("x", "y", "z")
    ]
    velocity_squared = sum(value * value for value in relative_velocity)
    if velocity_squared < 1e-8:
        return float("inf"), math.sqrt(
            sum(value * value for value in relative_position)
        )
    ttc = -sum(
        position * velocity
        for position, velocity in zip(relative_position, relative_velocity)
    ) / velocity_squared
    closest = [
        position + ttc * velocity
        for position, velocity in zip(relative_position, relative_velocity)
    ]
    return float(ttc), math.sqrt(sum(value * value for value in closest))
