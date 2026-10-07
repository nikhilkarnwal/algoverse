"""Declarative, deterministic collision and red-light scenario runtime."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml


SUPPORTED_FAMILIES = {
    "lead_vehicle_sudden_braking",
    "cross_traffic_conflict",
    "cut_in_lane_intrusion",
    "occluded_late_emergence",
    "red_light_straight_approach",
    "red_light_transition",
}


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    family: str
    hazard: str
    parameters: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "hazard": self.hazard,
            "parameters": dict(self.parameters),
        }


class ScenarioCatalog:
    def __init__(self, scenarios: Mapping[str, ScenarioSpec]):
        self._scenarios = dict(scenarios)

    @classmethod
    def load(cls, path: Path) -> "ScenarioCatalog":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_scenarios = data.get("scenarios", {}) if isinstance(data, dict) else {}
        if not isinstance(raw_scenarios, dict) or not raw_scenarios:
            raise ValueError("Scenario catalog must contain a non-empty scenarios mapping")

        scenarios = {}
        for name, value in raw_scenarios.items():
            family = str(value.get("family", ""))
            if family not in SUPPORTED_FAMILIES:
                raise ValueError(
                    "Scenario {} uses unsupported family {}".format(name, family)
                )
            hazard = str(value.get("hazard", ""))
            if hazard not in {"collision", "red_light"}:
                raise ValueError(
                    "Scenario {} must use collision or red_light hazard".format(name)
                )
            scenarios[name] = ScenarioSpec(
                name=name,
                family=family,
                hazard=hazard,
                parameters=dict(value.get("parameters", {})),
            )
        return cls(scenarios)

    def get(self, name: str) -> ScenarioSpec:
        try:
            return self._scenarios[name]
        except KeyError as error:
            raise KeyError(
                "Unknown scenario {!r}; available: {}".format(
                    name,
                    ", ".join(sorted(self._scenarios)),
                )
            ) from error

    def names(self) -> List[str]:
        return sorted(self._scenarios)


class ScenarioRuntime:
    """Spawn and control deterministic actors from one scenario specification."""

    def __init__(self, world: Any, ego_vehicle: Any, spec: ScenarioSpec):
        self.world = world
        self.ego_vehicle = ego_vehicle
        self.spec = spec
        self.actors: List[Any] = []
        self._traffic_light = None
        self._traffic_light_original_state = None
        self._current_control = None

    def start(self) -> None:
        if self.spec.hazard == "red_light":
            self._configure_traffic_light()
        if self.spec.family in {
            "lead_vehicle_sudden_braking",
            "cross_traffic_conflict",
            "cut_in_lane_intrusion",
            "occluded_late_emergence",
        } or bool(self.spec.parameters.get("lead_vehicle", False)):
            self._spawn_scripted_vehicle()

    def update(self, step: int) -> None:
        if self.spec.family == "red_light_transition" and self._traffic_light is not None:
            transition_step = int(self.spec.parameters.get("transition_step", 20))
            if step == transition_step:
                self._set_light_red()

        if not self.actors:
            return
        import carla

        trigger_step = int(self.spec.parameters.get("trigger_step", 30))
        if self.spec.family == "lead_vehicle_sudden_braking" and step >= trigger_step:
            self._current_control = carla.VehicleControl(throttle=0.0, brake=1.0)
        elif self.spec.family == "cut_in_lane_intrusion" and step >= trigger_step:
            self._current_control = carla.VehicleControl(
                throttle=float(self.spec.parameters.get("trigger_throttle", 0.25)),
                steer=float(self.spec.parameters.get("trigger_steer", -0.45)),
            )
        elif self.spec.family == "occluded_late_emergence" and step < trigger_step:
            self._current_control = carla.VehicleControl(throttle=0.0, brake=1.0)
        elif self._current_control is None or step == trigger_step:
            self._current_control = carla.VehicleControl(
                throttle=float(self.spec.parameters.get("initial_throttle", 0.35)),
                brake=0.0,
            )

        for actor in self.actors:
            if actor.is_alive:
                actor.apply_control(self._current_control)

    def close(self) -> None:
        if self._traffic_light is not None:
            try:
                self._traffic_light.freeze(False)
                if self._traffic_light_original_state is not None:
                    self._traffic_light.set_state(self._traffic_light_original_state)
            finally:
                self._traffic_light = None
        for actor in reversed(self.actors):
            try:
                if actor.is_alive:
                    actor.destroy()
            except Exception:
                pass
        self.actors = []

    def _spawn_scripted_vehicle(self) -> None:
        import carla

        parameters = self.spec.parameters
        longitudinal = float(parameters.get("longitudinal_m", 18.0))
        lateral = float(parameters.get("lateral_m", 0.0))
        yaw_offset = float(parameters.get("yaw_offset_degrees", 0.0))
        ego_transform = self.ego_vehicle.get_transform()
        yaw_radians = math.radians(ego_transform.rotation.yaw)
        location = carla.Location(
            x=ego_transform.location.x
            + longitudinal * math.cos(yaw_radians)
            - lateral * math.sin(yaw_radians),
            y=ego_transform.location.y
            + longitudinal * math.sin(yaw_radians)
            + lateral * math.cos(yaw_radians),
            z=ego_transform.location.z + 0.5,
        )
        transform = carla.Transform(
            location,
            carla.Rotation(yaw=ego_transform.rotation.yaw + yaw_offset),
        )
        waypoint = self.world.get_map().get_waypoint(
            location,
            project_to_road=True,
            lane_type=carla.LaneType.Driving,
        )
        if waypoint is not None and abs(yaw_offset) < 1e-6:
            transform = waypoint.transform
            transform.location.z += 0.5

        blueprint_id = str(parameters.get("blueprint", "vehicle.tesla.model3"))
        blueprint = self.world.get_blueprint_library().find(blueprint_id)
        blueprint.set_attribute("role_name", "scenario")
        actor = self.world.try_spawn_actor(blueprint, transform)
        if actor is None:
            raise RuntimeError(
                "Unable to spawn actor for scenario {} at its configured offset".format(
                    self.spec.name
                )
            )
        self.actors.append(actor)

    def _configure_traffic_light(self) -> None:
        lights = list(self.world.get_actors().filter("traffic.traffic_light*"))
        if not lights:
            raise RuntimeError("The loaded map does not expose traffic lights")
        ego_transform = self.ego_vehicle.get_transform()
        ego_location = ego_transform.location
        forward = ego_transform.get_forward_vector()
        lights_ahead = [
            light for light in lights
            if (
                (light.get_location().x - ego_location.x) * forward.x
                + (light.get_location().y - ego_location.y) * forward.y
            ) > 0.0
        ]
        light = min(
            lights_ahead or lights,
            key=lambda item: item.get_location().distance(ego_location),
        )
        self._traffic_light = light
        self._traffic_light_original_state = light.state
        light.freeze(True)
        if self.spec.family == "red_light_straight_approach":
            self._set_light_red()
        else:
            import carla

            light.set_state(carla.TrafficLightState.Green)

    def _set_light_red(self) -> None:
        import carla

        self._traffic_light.set_state(carla.TrafficLightState.Red)
