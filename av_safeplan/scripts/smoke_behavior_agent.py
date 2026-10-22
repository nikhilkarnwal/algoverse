#!/usr/bin/env python3
"""Run a deterministic Behavior Agent route and optionally record RGB frames."""

import argparse
from dataclasses import replace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.carla.synchronous import SynchronousWorld
from av_safeplan.carla.recording import RgbTrajectoryRecorder, create_run_directory
from av_safeplan.carla.determinism import (
    RoutePlan,
    apply_deterministic_seeds,
    build_run_manifest,
    route_manifest,
    select_route_plan,
    write_run_manifest,
)
from av_safeplan.carla.observations import collect_observation
from av_safeplan.environment.checks import apply_python_paths
from av_safeplan.policies.behavior import BehaviorAgentPolicy
from av_safeplan.safety.events import SafetyEventMonitor
from av_safeplan.safety.supervisor import PassthroughSupervisor
from av_safeplan.scenarios.catalog import ScenarioCatalog, ScenarioRuntime
from av_safeplan.settings import load_stack
from av_safeplan.telemetry.episode import EpisodeLogger


def select_vehicle_blueprint(world):
    blueprints = list(world.get_blueprint_library().filter("vehicle.*"))
    if not blueprints:
        raise RuntimeError("CARLA returned no vehicle blueprints")
    preferred = [item for item in blueprints if item.id == "vehicle.tesla.model3"]
    return preferred[0] if preferred else sorted(blueprints, key=lambda item: item.id)[0]


def spawn_ego(world, route: RoutePlan, spawn_points):
    blueprint = select_vehicle_blueprint(world)
    blueprint.set_attribute("role_name", "hero")
    actor = world.try_spawn_actor(blueprint, spawn_points[route.spawn_index])
    if actor is None:
        raise RuntimeError(
            "Unable to spawn the ego vehicle at route {}. The deterministic "
            "spawn point may be occupied; reload the map before replaying.".format(
                route.route_id
            )
        )
    return actor, spawn_points[route.destination_index].location


def settle_ego(world, actor, settle_steps: int) -> None:
    """Let vehicle physics settle before policy state and recording begin."""
    import carla

    actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
    for _ in range(settle_steps):
        world.tick()
    actor.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
    actor.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))
    actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--map", dest="map_name", default=None, help="Override the configured map")
    parser.add_argument("--seed", type=int, default=None, help="Override the configured run seed")
    parser.add_argument(
        "--reload-world",
        action="store_true",
        help="Reload the selected map before spawning actors for a clean replay state",
    )
    parser.add_argument(
        "--settle-steps",
        type=int,
        default=None,
        help="Synchronous brake-held ticks before policy initialization",
    )
    parser.add_argument(
        "--spawn-index",
        type=int,
        default=None,
        help="Replay an explicit CARLA spawn-point index",
    )
    parser.add_argument(
        "--destination-index",
        type=int,
        default=None,
        help="Replay an explicit CARLA destination spawn-point index",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Root directory for trajectory runs (defaults to the stack configuration)",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional directory name for this run; existing directories are not overwritten",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Run the route without attaching the trajectory camera",
    )
    parser.add_argument("--image-width", type=int, default=None)
    parser.add_argument("--image-height", type=int, default=None)
    parser.add_argument("--frame-stride", type=int, default=None)
    parser.add_argument(
        "--scenario",
        default=None,
        help="Controlled scenario name from the scenario catalog",
    )
    parser.add_argument(
        "--scenario-config",
        type=Path,
        default=PROJECT_ROOT / "config" / "scenarios.yaml",
    )
    parser.add_argument("--observation-radius", type=float, default=50.0)
    arguments = parser.parse_args()

    settings = load_stack(arguments.config)
    target_map = arguments.map_name or settings.carla.map_name
    run_seed = arguments.seed if arguments.seed is not None else settings.carla.seed
    steps = arguments.steps if arguments.steps is not None else settings.smoke.steps
    settle_steps = (
        arguments.settle_steps
        if arguments.settle_steps is not None
        else settings.smoke.settle_steps
    )
    if steps < 1:
        parser.error("--steps must be at least 1")
    if settle_steps < 0:
        parser.error("--settle-steps cannot be negative")
    if arguments.observation_radius <= 0:
        parser.error("--observation-radius must be positive")
    recording_settings = replace(
        settings.recording,
        image_width=(
            arguments.image_width
            if arguments.image_width is not None
            else settings.recording.image_width
        ),
        image_height=(
            arguments.image_height
            if arguments.image_height is not None
            else settings.recording.image_height
        ),
        frame_stride=(
            arguments.frame_stride
            if arguments.frame_stride is not None
            else settings.recording.frame_stride
        ),
    )
    if recording_settings.image_width < 1 or recording_settings.image_height < 1:
        parser.error("image dimensions must be positive")
    if recording_settings.frame_stride < 1:
        parser.error("--frame-stride must be at least 1")
    apply_python_paths(settings)

    import carla

    client = carla.Client(settings.carla.host, settings.carla.port)
    client.set_timeout(settings.carla.timeout_seconds)
    server_version = client.get_server_version()
    client_version = client.get_client_version()
    if server_version != settings.carla.version:
        raise RuntimeError(
            "CARLA server version {} does not match pinned {}".format(
                server_version, settings.carla.version
            )
        )

    available_maps = client.get_available_maps()
    expected_suffix = "/{}".format(target_map)
    if not any(
        item == target_map or item.endswith(expected_suffix)
        for item in available_maps
    ):
        available_names = sorted(item.rsplit("/", 1)[-1] for item in available_maps)
        raise RuntimeError(
            "Map {!r} is not installed. Available maps: {}. "
            "On Colab run scripts/install_carla_maps_colab.sh first.".format(
                target_map,
                ", ".join(available_names) or "none",
            )
        )
    current_world = client.get_world()
    current_map_name = current_world.get_map().name.rsplit("/", 1)[-1]
    world_reset = False
    if current_map_name == target_map and arguments.reload_world:
        print(
            "Reloading map {} with a {:.0f}-second timeout...".format(
                target_map,
                settings.carla.map_load_timeout_seconds,
            )
        )
        client.set_timeout(settings.carla.map_load_timeout_seconds)
        try:
            world = client.reload_world()
        finally:
            client.set_timeout(settings.carla.timeout_seconds)
        world_reset = True
    elif current_map_name == target_map:
        print("Reusing already loaded map {}.".format(target_map))
        world = current_world
    else:
        print(
            "Loading map {} with a {:.0f}-second timeout...".format(
                target_map,
                settings.carla.map_load_timeout_seconds,
            )
        )
        client.set_timeout(settings.carla.map_load_timeout_seconds)
        try:
            world = client.load_world(target_map)
        finally:
            client.set_timeout(settings.carla.timeout_seconds)
        world_reset = True
    traffic_manager = client.get_trafficmanager(settings.carla.traffic_manager_port)
    apply_deterministic_seeds(world, traffic_manager, run_seed)
    spawn_points = list(world.get_map().get_spawn_points())
    route = select_route_plan(
        target_map,
        spawn_points,
        run_seed,
        spawn_index=arguments.spawn_index,
        destination_index=arguments.destination_index,
    )
    route_data = route_manifest(route, spawn_points)
    scenario_spec = None
    if arguments.scenario:
        scenario_spec = ScenarioCatalog.load(arguments.scenario_config).get(
            arguments.scenario
        )

    output_root = arguments.output_dir or settings.recording.output_root
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    run_directory = create_run_directory(
        output_root.resolve(),
        target_map,
        run_seed,
        arguments.run_name,
    )
    recording_enabled = settings.recording.enabled and not arguments.no_images
    manifest_path = run_directory / "manifest.json"
    manifest = build_run_manifest(
        project=settings.project,
        seed=run_seed,
        route=route_data,
        fixed_delta_seconds=settings.carla.fixed_delta_seconds,
        requested_steps=steps,
        policy="behavior_agent",
        behavior=settings.smoke.behavior,
        carla_client_version=client_version,
        carla_server_version=server_version,
        recording={
            "enabled": recording_enabled,
            "frame_stride": recording_settings.frame_stride,
            "image_width": recording_settings.image_width,
            "image_height": recording_settings.image_height,
        },
    )
    manifest["scenario"] = scenario_spec.to_dict() if scenario_spec else None
    manifest["initialization"] = {
        "settle_steps": settle_steps,
        "world_reset": world_reset,
    }
    write_run_manifest(manifest_path, manifest)

    actor = None
    recorder = None
    policy = None
    event_monitor = None
    scenario_runtime = None
    episode_logger = None
    supervisor = PassthroughSupervisor()
    executed = 0
    destination_reached = False
    event_counts = {}

    try:
        with SynchronousWorld(world, traffic_manager, settings.carla.fixed_delta_seconds):
            try:
                actor, destination = spawn_ego(world, route, spawn_points)
                settle_ego(world, actor, settle_steps)
                policy = BehaviorAgentPolicy(
                    actor,
                    destination,
                    behavior=settings.smoke.behavior,
                    target_speed_mps=(
                        scenario_spec.parameters.get("approach_speed_mps")
                        if scenario_spec is not None
                        else None
                    ),
                )
                episode_logger = EpisodeLogger(
                    run_directory / "episode.jsonl",
                    seed=run_seed,
                    route=route_data,
                    policy_name=policy.name,
                    scenario=scenario_spec.to_dict() if scenario_spec else None,
                )
                event_monitor = SafetyEventMonitor(world, actor)
                event_monitor.start()

                if scenario_spec is not None:
                    scenario_runtime = ScenarioRuntime(world, actor, scenario_spec)
                    scenario_runtime.start()

                if recording_enabled:
                    recorder = RgbTrajectoryRecorder(
                        world,
                        actor,
                        recording_settings,
                        run_directory,
                    )
                    recorder.start()

                for _ in range(steps):
                    if scenario_runtime is not None:
                        scenario_runtime.update(executed)
                    world_frame = world.tick()
                    snapshot = world.get_snapshot()
                    observation = collect_observation(
                        world,
                        actor,
                        world_frame,
                        snapshot.timestamp.elapsed_seconds,
                        destination=destination,
                        radius_m=arguments.observation_radius,
                        route_id=route.route_id,
                    )
                    base_action = policy.act(observation)
                    decision = supervisor.supervise(observation, base_action, {})
                    actor.apply_control(decision.action.to_carla())
                    events = event_monitor.update(observation)
                    for event in events:
                        event_type = event["event_type"]
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1
                    episode_logger.append(
                        observation,
                        base_action,
                        decision.action,
                        events,
                        supervisor_intervened=decision.intervened,
                    )
                    if recorder is not None:
                        recorder.save_frame(
                            world_frame,
                            decision.action,
                            timeout_seconds=settings.carla.timeout_seconds,
                        )
                    executed += 1
                    if policy.done():
                        break
                destination_reached = policy.done()
            finally:
                if event_monitor is not None:
                    try:
                        event_monitor.close()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly destroy safety sensors: {}".format(
                                error
                            ),
                            file=sys.stderr,
                        )
                if recorder is not None:
                    try:
                        recorder.close()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly destroy RGB sensor: {}".format(error),
                            file=sys.stderr,
                        )
                if scenario_runtime is not None:
                    try:
                        scenario_runtime.close()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly destroy scenario actors: {}".format(
                                error
                            ),
                            file=sys.stderr,
                        )
                if policy is not None:
                    try:
                        policy.close()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly close policy: {}".format(error),
                            file=sys.stderr,
                        )
                if actor is not None:
                    try:
                        if actor.is_alive:
                            actor.destroy()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly destroy ego vehicle: {}".format(error),
                            file=sys.stderr,
                        )
    except Exception as error:
        manifest["outcome"] = {
            "status": "failed",
            "executed_steps": executed,
            "destination_reached": destination_reached,
            "event_counts": event_counts,
            "telemetry_records": (
                episode_logger.records_written if episode_logger is not None else 0
            ),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        write_run_manifest(manifest_path, manifest)
        raise

    manifest["outcome"] = {
        "status": "passed",
        "executed_steps": executed,
        "destination_reached": destination_reached,
        "event_counts": event_counts,
        "telemetry_records": (
            episode_logger.records_written if episode_logger is not None else 0
        ),
    }
    write_run_manifest(manifest_path, manifest)
    print(
        "Behavior Agent smoke run passed: {} ticks, destination_reached={}".format(
            executed,
            destination_reached,
        )
    )
    print("Route: {}".format(route.route_id))
    print("Run manifest: {}".format(manifest_path))
    if episode_logger is not None:
        print("Episode telemetry: {}".format(episode_logger.path))
    if recorder is not None:
        print("Saved {} trajectory images to {}".format(
            recorder.saved_images,
            run_directory,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
