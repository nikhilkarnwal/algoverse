#!/usr/bin/env python3
"""ScenarioRunner agent that keeps AV SafePlan policy, logging, and labels."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from srunner.autoagents.autonomous_agent import AutonomousAgent
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider

from av_safeplan.carla.observations import collect_observation
from av_safeplan.carla.recording import TrajectoryMetadataWriter, build_trajectory_record
from av_safeplan.policies.behavior import BehaviorAgentPolicy
from av_safeplan.safety.events import SafetyEventMonitor
from av_safeplan.safety.supervisor import PassthroughSupervisor
from av_safeplan.telemetry.episode import EpisodeLogger


def get_entry_point() -> str:
    return "ScenarioRunnerBehaviorAgent"


class ScenarioRunnerBehaviorAgent(AutonomousAgent):
    """Run Behavior Agent inside official ScenarioRunner route execution."""

    def setup(self, path_to_conf_file: str) -> None:
        del path_to_conf_file
        self._policy: Optional[BehaviorAgentPolicy] = None
        self._event_monitor: Optional[SafetyEventMonitor] = None
        self._episode_logger: Optional[EpisodeLogger] = None
        self._trajectory_writer: Optional[TrajectoryMetadataWriter] = None
        self._supervisor = PassthroughSupervisor()
        self._ego_vehicle = None
        self._world = None
        self._destination = None
        self._event_counts: Dict[str, int] = {}
        self._route_plan_points = 0
        self._route_geometry = []
        self._map_name = None
        self._fixed_delta_seconds = None
        self._saved_images = 0
        self._closed = False
        self._outcome = {"status": "running"}

        output_root = Path(os.environ.get(
            "AV_SAFEPLAN_SCENARIO_OUTPUT_ROOT",
            "outputs/scenario_runner",
        )).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        requested_name = os.environ.get("AV_SAFEPLAN_SCENARIO_RUN_NAME")
        if requested_name:
            run_name = _safe_component(requested_name)
        else:
            run_name = "scenario-runner-{}".format(
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
        self._run_directory = _unique_directory(output_root, run_name)
        self._rgb_directory = self._run_directory / "rgb"
        self._rgb_directory.mkdir()
        self._manifest_path = self._run_directory / "manifest.json"
        self._write_manifest()

    def sensors(self) -> Any:
        return [{
            "type": "sensor.camera.rgb",
            "x": 1.5,
            "y": 0.0,
            "z": 2.4,
            "roll": 0.0,
            "pitch": -8.0,
            "yaw": 0.0,
            "width": 640,
            "height": 360,
            "fov": 90,
            "id": "Center",
        }]

    def run_step(self, input_data: Dict[str, Any], timestamp: float) -> Any:
        try:
            self._ensure_initialized()
            snapshot = self._world.get_snapshot()
            frame = int(snapshot.frame)
            camera = input_data.get("Center")
            if not isinstance(camera, tuple) or len(camera) != 2:
                raise RuntimeError("Center camera must retain its actual sensor frame")
            sensor_frame = int(camera[0])
            if sensor_frame != frame:
                raise RuntimeError("Camera/world frame mismatch: {} != {}".format(sensor_frame, frame))
            timestamp_seconds = float(snapshot.timestamp.elapsed_seconds)
            sensor_summary = _sensor_summary(input_data)
            observation = collect_observation(
                self._world,
                self._ego_vehicle,
                frame,
                timestamp_seconds,
                destination=self._destination,
                route_id=os.environ.get("AV_SAFEPLAN_SCENARIO_ROUTE_ID"),
                sensors=sensor_summary,
            )
            base_action = self._policy.act(observation)
            decision = self._supervisor.supervise(observation, base_action, {})
            events = self._event_monitor.update(observation)
            for event in events:
                event_type = str(event.get("event_type", "unknown"))
                self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1

            self._episode_logger.append(
                observation,
                base_action,
                decision.action,
                events,
                supervisor_intervened=decision.intervened,
            )
            relative_image = self._save_rgb(input_data, frame)
            transform = self._ego_vehicle.get_transform()
            velocity = self._ego_vehicle.get_velocity()
            self._trajectory_writer.append(build_trajectory_record(
                world_frame=frame,
                sensor_frame=sensor_frame,
                timestamp_seconds=timestamp_seconds,
                image_path=relative_image,
                control=decision.action.to_dict(),
                location={
                    "x": transform.location.x,
                    "y": transform.location.y,
                    "z": transform.location.z,
                },
                rotation={
                    "pitch": transform.rotation.pitch,
                    "yaw": transform.rotation.yaw,
                    "roll": transform.rotation.roll,
                },
                velocity={"x": velocity.x, "y": velocity.y, "z": velocity.z},
            ))
            if self._episode_logger.records_written % 20 == 0:
                self._write_manifest()
            return decision.action.to_carla()
        except Exception as error:
            self._outcome = {"status": "failed", "error": repr(error)}
            self._write_manifest()
            raise

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._event_monitor is not None:
            self._event_monitor.close()
        if self._policy is not None:
            self._policy.close()
        if self._outcome.get("status") == "running":
            self._outcome = {
                "status": "completed",
                "note": "Use ScenarioRunner criteria JSON for the authoritative pass/fail result.",
            }
        self._write_manifest()

    def _ensure_initialized(self) -> None:
        if self._policy is not None:
            return
        self._world = CarlaDataProvider.get_world()
        self._map_name = self._world.get_map().name
        self._fixed_delta_seconds = self._world.get_settings().fixed_delta_seconds
        for actor in self._world.get_actors().filter("vehicle.*"):
            if actor.attributes.get("role_name") == "hero":
                self._ego_vehicle = actor
                break
        if self._ego_vehicle is None:
            raise RuntimeError("ScenarioRunner hero vehicle is unavailable")
        if not self._global_plan_world_coord:
            raise RuntimeError("ScenarioRunner did not provide a world-coordinate route plan")
        destination_transform = self._global_plan_world_coord[-1][0]
        self._destination = destination_transform.location
        behavior_plan = []
        carla_map = self._world.get_map()
        for transform, road_option in self._global_plan_world_coord:
            location = (
                transform.location
                if hasattr(transform, "location")
                else transform.transform.location
            )
            waypoint = carla_map.get_waypoint(location)
            if waypoint is None:
                raise RuntimeError("ScenarioRunner route contains an unmapped waypoint")
            behavior_plan.append((waypoint, road_option))
        self._route_plan_points = len(behavior_plan)
        self._route_geometry = [
            {"x": float(waypoint.transform.location.x), "y": float(waypoint.transform.location.y),
             "z": float(waypoint.transform.location.z)} for waypoint, _ in behavior_plan
        ]
        self._policy = BehaviorAgentPolicy(
            self._ego_vehicle,
            destination=self._destination,
            global_plan=behavior_plan,
        )
        self._event_monitor = SafetyEventMonitor(self._world, self._ego_vehicle)
        self._event_monitor.start()
        seed = int(os.environ.get("AV_SAFEPLAN_SCENARIO_SEED", "0"))
        route = {
            "route_id": os.environ.get("AV_SAFEPLAN_SCENARIO_ROUTE_ID", "scenario-runner"),
            "map": self._world.get_map().name,
        }
        self._episode_logger = EpisodeLogger(
            self._run_directory / "episode.jsonl",
            seed=seed,
            route=route,
            policy_name=self._policy.name,
            scenario={"backend": "scenario_runner", "source": "public_route_xml"},
        )
        self._trajectory_writer = TrajectoryMetadataWriter(
            self._run_directory / "trajectory.jsonl"
        )
        self._write_manifest()

    def _save_rgb(self, input_data: Dict[str, Any], frame: int) -> Path:
        relative_path = Path("rgb") / "frame_{:06d}.png".format(frame)
        output_path = self._run_directory / relative_path
        value = input_data.get("Center")
        image = value[1] if isinstance(value, tuple) and len(value) == 2 else value
        if image is None:
            return Path("")
        if hasattr(image, "save_to_disk"):
            image.save_to_disk(str(output_path))
        else:
            from PIL import Image
            array = image[:, :, :3]
            Image.fromarray(array[:, :, ::-1]).save(str(output_path))
        self._saved_images += 1
        return relative_path

    def _write_manifest(self) -> None:
        payload = {
            "backend": "scenario_runner",
            "policy": "behavior_agent",
            "route_id": os.environ.get("AV_SAFEPLAN_SCENARIO_ROUTE_ID"),
            "seed": int(os.environ.get("AV_SAFEPLAN_SCENARIO_SEED", "0")),
            "seed_application": {
                "python_numpy_provider": os.environ.get("AV_SAFEPLAN_PROCESS_SEED_APPLIED") == "1",
                "traffic_manager": "see collection command --trafficManagerSeed",
                "pedestrian_seed": "not explicitly set; no deterministic replay claim",
            },
            "event_counts": dict(sorted(self._event_counts.items())),
            "route_plan_points": self._route_plan_points,
            "route_geometry": self._route_geometry,
            "map": self._map_name,
            "fixed_delta_seconds": self._fixed_delta_seconds,
            "sensor_timing": {"source": "sensor_callback_frame", "camera": "Center", "strict_alignment": True},
            "detectors": {"collision": "carla_collision_sensor", "red_light_violation": "trigger_exit_heuristic_v1"},
            "source_routes": os.environ.get("AV_SAFEPLAN_SOURCE_ROUTES"),
            "saved_images": self._saved_images,
            "episode_records": (
                self._episode_logger.records_written
                if self._episode_logger is not None else 0
            ),
            "trajectory_records": (
                self._trajectory_writer.records_written
                if self._trajectory_writer is not None else 0
            ),
            "outcome": self._outcome,
            "authoritative_result": "ScenarioRunner criteria JSON",
        }
        temporary = self._manifest_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._manifest_path)


def _sensor_summary(input_data: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for name, value in input_data.items():
        sensor = value[1] if isinstance(value, tuple) and len(value) == 2 else value
        shape = getattr(sensor, "shape", None)
        summary[name] = {"shape": list(shape)} if shape is not None else {"available": True}
    return summary


def _safe_component(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    cleaned = cleaned.strip("-")
    if not cleaned:
        raise ValueError("AV_SAFEPLAN_SCENARIO_RUN_NAME must contain a letter or digit")
    return cleaned


def _unique_directory(root: Path, name: str) -> Path:
    for suffix in range(1000):
        candidate = root / (name if suffix == 0 else "{}-{}".format(name, suffix))
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique ScenarioRunner output directory")
