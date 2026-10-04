#!/usr/bin/env python3
"""Run a deterministic Behavior Agent smoke route in Town12."""

import argparse
from pathlib import Path
import random
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.carla.synchronous import SynchronousWorld
from av_safeplan.carla.recording import RgbTrajectoryRecorder, create_run_directory
from av_safeplan.environment.checks import apply_python_paths
from av_safeplan.settings import load_stack


def select_vehicle_blueprint(world):
    blueprints = list(world.get_blueprint_library().filter("vehicle.*"))
    if not blueprints:
        raise RuntimeError("CARLA returned no vehicle blueprints")
    preferred = [item for item in blueprints if item.id == "vehicle.tesla.model3"]
    return preferred[0] if preferred else sorted(blueprints, key=lambda item: item.id)[0]


def spawn_ego(world, seed):
    points = list(world.get_map().get_spawn_points())
    if len(points) < 2:
        raise RuntimeError("Town does not provide enough spawn points")
    rng = random.Random(seed)
    ordered = list(points)
    rng.shuffle(ordered)
    blueprint = select_vehicle_blueprint(world)
    blueprint.set_attribute("role_name", "hero")
    for point in ordered:
        actor = world.try_spawn_actor(blueprint, point)
        if actor is not None:
            destination = max(
                points,
                key=lambda candidate: candidate.location.distance(point.location),
            )
            return actor, destination.location
    raise RuntimeError("Unable to spawn the ego vehicle")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--steps", type=int, default=None)
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
    arguments = parser.parse_args()

    settings = load_stack(arguments.config)
    apply_python_paths(settings)

    import carla
    from agents.navigation.behavior_agent import BehaviorAgent

    client = carla.Client(settings.carla.host, settings.carla.port)
    client.set_timeout(settings.carla.timeout_seconds)
    server_version = client.get_server_version()
    if server_version != settings.carla.version:
        raise RuntimeError(
            "CARLA server version {} does not match pinned {}".format(
                server_version, settings.carla.version
            )
        )

    world = client.load_world(settings.carla.map_name)
    traffic_manager = client.get_trafficmanager(settings.carla.traffic_manager_port)
    traffic_manager.set_random_device_seed(settings.carla.seed)
    actor = None
    recorder = None
    run_directory = None
    steps = arguments.steps or settings.smoke.steps

    try:
        with SynchronousWorld(world, traffic_manager, settings.carla.fixed_delta_seconds):
            actor, destination = spawn_ego(world, settings.carla.seed)
            agent = BehaviorAgent(actor, behavior=settings.smoke.behavior)
            agent.set_destination(destination)

            recording_enabled = settings.recording.enabled and not arguments.no_images
            if recording_enabled:
                output_root = arguments.output_dir or settings.recording.output_root
                if not output_root.is_absolute():
                    output_root = PROJECT_ROOT / output_root
                run_directory = create_run_directory(
                    output_root.resolve(),
                    settings.carla.map_name,
                    settings.carla.seed,
                    arguments.run_name,
                )
                recorder = RgbTrajectoryRecorder(
                    world,
                    actor,
                    settings.recording,
                    run_directory,
                )
                recorder.start()

            executed = 0
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

            print("Behavior Agent smoke run passed: {} ticks, destination_reached={}".format(
                executed, agent.done()
            ))
            if recorder is not None:
                print("Saved {} trajectory images to {}".format(
                    recorder.saved_images, run_directory
                ))
    finally:
        try:
            if recorder is not None:
                recorder.close()
        finally:
            if actor is not None and actor.is_alive:
                actor.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
