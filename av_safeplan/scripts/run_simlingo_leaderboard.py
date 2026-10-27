#!/usr/bin/env python3
"""Run the pinned SimLingo agent through its official Leaderboard evaluator."""

import argparse
import importlib.util
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
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--no-recording", action="store_true", help="Run the upstream baseline without shared episode recording")
    parser.add_argument("--no-images", action="store_true", help="Record shared telemetry but omit PNG frames and MP4")
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
        PROJECT_ROOT / "scripts" / "simlingo_evaluation_agent.py",
        "SimLingo agent",
    )
    checkpoint = required_file(settings.simlingo.checkpoint, "SimLingo checkpoint")
    routes = required_file(arguments.routes, "Leaderboard routes file")
    output_directory = arguments.output_dir.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    # Upstream tick() loads conversation.py relative to the working directory,
    # separately from Transformers' HF cache. Expose the cached snapshot without
    # downloading another copy or modifying the pinned upstream checkout.
    from huggingface_hub import snapshot_download
    from omegaconf import OmegaConf

    model_config = OmegaConf.load(checkpoint.parent.parent.parent / ".hydra" / "config.yaml")
    variant = str(model_config.model.vision_model.variant)
    snapshot = Path(snapshot_download(repo_id=variant, local_files_only=True)).resolve()
    conversation = snapshot / "conversation.py"
    required_file(conversation, "Cached conversation module")
    local_model = output_directory / "pretrained" / variant.rsplit("/", 1)[-1]
    local_model.parent.mkdir(parents=True, exist_ok=True)
    if local_model.exists() or local_model.is_symlink():
        if local_model.resolve() != snapshot:
            raise RuntimeError("Existing model path points to a different snapshot: {}".format(local_model))
    else:
        local_model.symlink_to(snapshot, target_is_directory=True)
    spec = importlib.util.spec_from_file_location("safeplan_conversation_preflight", conversation)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print("Cached model snapshot: {}".format(snapshot), flush=True)
    if arguments.preflight_only:
        from simlingo_evaluation_agent import SafePlanLingoAgent
        print("Conversation module and evaluation agent imports passed; CARLA not contacted.", flush=True)
        return 0

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
    environment["SAVE_PATH"] = ""
    environment["AV_SAFEPLAN_SIMLINGO_OUTPUT"] = str(output_directory)
    environment["AV_SAFEPLAN_SIMLINGO_ROUTE_SUBSET"] = arguments.routes_subset
    environment["AV_SAFEPLAN_SIMLINGO_SEED"] = str(settings.carla.seed)
    environment["AV_SAFEPLAN_SIMLINGO_RECORD"] = "0" if arguments.no_recording else "1"
    environment["AV_SAFEPLAN_SIMLINGO_IMAGES"] = "0" if arguments.no_images else "1"
    completed = subprocess.run(command, env=environment, cwd=str(output_directory), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
