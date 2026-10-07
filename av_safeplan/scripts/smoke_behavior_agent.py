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
from av_safeplan.environment.checks import apply_python_paths
from av_safeplan.settings import load_stack


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--map", dest="map_name", default=None, help="Override the configured map")
    parser.add_argument("--seed", type=int, default=None, help="Override the configured run seed")
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
    arguments = parser.parse_args()

    settings = load_stack(arguments.config)
    target_map = arguments.map_name or settings.carla.map_name
    run_seed = arguments.seed if arguments.seed is not None else settings.carla.seed
    steps = arguments.steps if arguments.steps is not None else settings.smoke.steps
    if steps < 1:
        parser.error("--steps must be at least 1")
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
    from agents.navigation.behavior_agent import BehaviorAgent

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
    if current_map_name == target_map:
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
        world = client.load_world(target_map)
        client.set_timeout(settings.carla.timeout_seconds)
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
        route=route_manifest(route, spawn_points),
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
    write_run_manifest(manifest_path, manifest)

    actor = None
    recorder = None
    executed = 0
    destination_reached = False

    try:
        with SynchronousWorld(world, traffic_manager, settings.carla.fixed_delta_seconds):
            try:
                actor, destination = spawn_ego(world, route, spawn_points)
                agent = BehaviorAgent(actor, behavior=settings.smoke.behavior)
                agent.set_destination(destination)

                if recording_enabled:
                    recorder = RgbTrajectoryRecorder(
                        world,
                        actor,
                        recording_settings,
                        run_directory,
                    )
                    recorder.start()

                for _ in range(steps):
                    world_frame = world.tick()
                    control = agent.run_step()
                    if not isinstance(control, carla.VehicleControl):
                        raise TypeError("Behavior Agent returned an invalid control object")
                    actor.apply_control(control)
                    if recorder is not None:
                        recorder.save_frame(
                            world_frame,
                            control,
                            timeout_seconds=settings.carla.timeout_seconds,
                        )
                    executed += 1
                    if agent.done():
                        break
                destination_reached = agent.done()
            finally:
                if recorder is not None:
                    try:
                        recorder.close()
                    except Exception as error:
                        print(
                            "Warning: could not cleanly destroy RGB sensor: {}".format(error),
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
            "error_type": type(error).__name__,
            "error": str(error),
        }
        write_run_manifest(manifest_path, manifest)
        raise

    manifest["outcome"] = {
        "status": "passed",
        "executed_steps": executed,
        "destination_reached": destination_reached,
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
    if recorder is not None:
        print("Saved {} trajectory images to {}".format(
            recorder.saved_images,
            run_directory,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
