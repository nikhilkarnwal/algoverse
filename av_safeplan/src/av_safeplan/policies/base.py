"""Backend-neutral observation-to-control policy contract."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class VehicleControlCommand:
    """Normalized steering, throttle, and brake command."""

    steer: float
    throttle: float
    brake: float
    hand_brake: bool = False
    reverse: bool = False

    def __post_init__(self) -> None:
        if not -1.0 <= self.steer <= 1.0:
            raise ValueError("steer must be between -1 and 1")
        if not 0.0 <= self.throttle <= 1.0:
            raise ValueError("throttle must be between 0 and 1")
        if not 0.0 <= self.brake <= 1.0:
            raise ValueError("brake must be between 0 and 1")

    @classmethod
    def from_carla(cls, control: Any) -> "VehicleControlCommand":
        return cls(
            steer=float(control.steer),
            throttle=float(control.throttle),
            brake=float(control.brake),
            hand_brake=bool(control.hand_brake),
            reverse=bool(control.reverse),
        )

    def to_carla(self) -> Any:
        import carla

        return carla.VehicleControl(**asdict(self))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyObservation:
    """Shared observation envelope for classical and learned policies."""

    frame: int
    timestamp_seconds: float
    ego: Mapping[str, Any]
    nearby_actors: Mapping[str, Any] = field(default_factory=dict)
    traffic_lights: Mapping[str, Any] = field(default_factory=dict)
    route: Mapping[str, Any] = field(default_factory=dict)
    sensors: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class BasePolicy(ABC):
    """Minimal policy lifecycle shared by all driving backends."""

    name = "base"

    @abstractmethod
    def act(self, observation: PolicyObservation) -> VehicleControlCommand:
        """Produce one vehicle command for the supplied observation."""

    def done(self) -> bool:
        return False

    def close(self) -> None:
        """Release policy resources."""
