#!/usr/bin/env python3
"""Run the pinned SimLingo agent through its official Leaderboard evaluator."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.environment.checks import apply_python_paths
from av_safeplan.settings import load_stack


def required_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError("{} not found: {}".format(description, resolved))
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--routes-subset", default="")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--debug", type=int, default=0)
    arguments = parser.parse_args()
    if arguments.repetitions < 1:
        parser.error("--repetitions must be at least 1")

    settings = load_stack(arguments.config)
    apply_python_paths(settings)
    if settings.simlingo.root is None:
        raise RuntimeError("SIMLINGO_ROOT is not configured")
    if settings.simlingo.checkpoint is None:
        raise RuntimeError("SIMLINGO_CHECKPOINT is not configured")

    simlingo_root = settings.simlingo.root
    evaluator = required_file(
        simlingo_root / "leaderboard" / "leaderboard" / "leaderboard_evaluator.py",
        "SimLingo Leaderboard evaluator",
    )
    agent = required_file(
        simlingo_root / "team_code" / "agent_simlingo.py",
        "SimLingo agent",
    )
    checkpoint = required_file(settings.simlingo.checkpoint, "SimLingo checkpoint")
    routes = required_file(arguments.routes, "Leaderboard routes file")
    output_directory = arguments.output_dir.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(evaluator),
        "--host", settings.carla.host,
        "--port", str(settings.carla.port),
        "--traffic-manager-port", str(settings.carla.traffic_manager_port),
        "--traffic-manager-seed", str(settings.carla.seed),
        "--routes", str(routes),
        "--repetitions", str(arguments.repetitions),
        "--agent", str(agent),
        "--agent-config", "{}+{}".format(checkpoint, output_directory),
        "--checkpoint", str(output_directory / "simulation_results.json"),
        "--debug-checkpoint", str(output_directory / "live_results.txt"),
        "--debug", str(arguments.debug),
        "--timeout", str(settings.carla.map_load_timeout_seconds),
    ]
    if arguments.routes_subset:
        command.extend(["--routes-subset", arguments.routes_subset])

    environment = os.environ.copy()
    environment["ROUTES"] = str(routes)
    environment["WORK_DIR"] = str(simlingo_root)
    environment["SCENARIO_RUNNER_ROOT"] = str(simlingo_root / "scenario_runner")
    environment["LEADERBOARD_ROOT"] = str(simlingo_root / "leaderboard")
    completed = subprocess.run(command, env=environment, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
