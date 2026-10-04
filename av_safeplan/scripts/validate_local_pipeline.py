#!/usr/bin/env python3
"""Validate the trajectory pipeline locally with a deterministic CPU-only drive."""

import argparse
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Dict, List

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.carla.recording import (
    TrajectoryMetadataWriter,
    build_trajectory_record,
    create_run_directory,
)
from av_safeplan.settings import load_stack


def synthetic_state(frame: int, delta_seconds: float) -> Dict[str, Dict[str, Any]]:
    """Return a deterministic policy action and ego state for one frame."""
    timestamp = frame * delta_seconds
    speed = 6.0 + 0.5 * math.sin(frame / 4.0)
    steer = 0.18 * math.sin(frame / 5.0)
    yaw = 4.0 * math.sin(frame / 7.0)
    return {
        "control": {
            "steer": steer,
            "throttle": 0.35,
            "brake": 0.0,
            "hand_brake": False,
            "reverse": False,
        },
        "location": {
            "x": speed * timestamp,
            "y": 1.5 * math.sin(frame / 7.0),
            "z": 0.0,
        },
        "rotation": {"pitch": 0.0, "yaw": yaw, "roll": 0.0},
        "velocity": {
            "x": speed * math.cos(math.radians(yaw)),
            "y": speed * math.sin(math.radians(yaw)),
            "z": 0.0,
        },
    }


def render_frame(width: int, height: int, frame: int, steer: float) -> Image.Image:
    """Render a small deterministic road scene without simulator dependencies."""
    image = Image.new("RGB", (width, height), (126, 181, 219))
    draw = ImageDraw.Draw(image)
    horizon = int(height * 0.42)
    draw.rectangle((0, horizon, width, height), fill=(66, 70, 74))
    draw.rectangle((0, horizon - 6, width, horizon), fill=(83, 139, 73))

    center = width // 2 + int(steer * width * 0.15)
    lane_half_top = max(8, width // 24)
    lane_half_bottom = width // 3
    draw.polygon(
        [
            (center - lane_half_top, horizon),
            (center + lane_half_top, horizon),
            (center + lane_half_bottom, height),
            (center - lane_half_bottom, height),
        ],
        fill=(45, 47, 50),
    )
    dash_offset = (frame * max(4, height // 40)) % max(12, height // 8)
    for y in range(horizon + dash_offset, height, max(18, height // 7)):
        progress = (y - horizon) / max(1, height - horizon)
        dash_width = max(2, int(2 + progress * width * 0.01))
        dash_height = max(5, int(6 + progress * height * 0.05))
        draw.rectangle(
            (center - dash_width, y, center + dash_width, min(height, y + dash_height)),
            fill=(242, 219, 92),
        )
    draw.text((16, 14), "AV SafePlan local CPU frame {:04d}".format(frame), fill=(15, 20, 25))
    return image


def validate_outputs(
    run_directory: Path,
    expected_frames: List[int],
    width: int,
    height: int,
) -> Dict[str, Any]:
    metadata_path = run_directory / "trajectory.jsonl"
    records = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines()]
    actual_frames = [record["world_frame"] for record in records]
    if actual_frames != expected_frames:
        raise RuntimeError(
            "Frame sequence mismatch: expected {}, found {}".format(expected_frames, actual_frames)
        )

    required_top_level = {"world_frame", "sensor_frame", "timestamp_seconds", "image", "control", "ego"}
    for record in records:
        missing = required_top_level.difference(record)
        if missing:
            raise RuntimeError("Trajectory record is missing keys: {}".format(sorted(missing)))
        image_path = run_directory / record["image"]
        if not image_path.is_file():
            raise RuntimeError("Recorded image does not exist: {}".format(image_path))
        with Image.open(str(image_path)) as image:
            image.load()
            if image.size != (width, height) or image.mode != "RGB":
                raise RuntimeError(
                    "Unexpected image format at {}: size={}, mode={}".format(
                        image_path, image.size, image.mode
                    )
                )

    return {
        "status": "pass",
        "records": len(records),
        "images": len(list((run_directory / "rgb").glob("*.png"))),
        "first_frame": actual_frames[0] if actual_frames else None,
        "last_frame": actual_frames[-1] if actual_frames else None,
        "image_size": [width, height],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "local-validation")
    parser.add_argument("--run-name", default=None)
    arguments = parser.parse_args()
    if arguments.steps < 1:
        parser.error("--steps must be at least 1")

    settings = load_stack(arguments.config)
    output_root = arguments.output_dir.expanduser().resolve()
    run_directory = create_run_directory(
        output_root,
        "synthetic_mac",
        settings.carla.seed,
        arguments.run_name,
    )
    metadata_writer = TrajectoryMetadataWriter(run_directory / "trajectory.jsonl")
    saved_frames: List[int] = []

    for frame in range(1, arguments.steps + 1):
        if frame % settings.recording.frame_stride != 0:
            continue
        state = synthetic_state(frame, settings.carla.fixed_delta_seconds)
        image_name = "frame_{:06d}.png".format(frame)
        relative_image_path = Path("rgb") / image_name
        image = render_frame(
            settings.recording.image_width,
            settings.recording.image_height,
            frame,
            float(state["control"]["steer"]),
        )
        image.save(str(run_directory / relative_image_path), format="PNG")
        record = build_trajectory_record(
            world_frame=frame,
            sensor_frame=frame,
            timestamp_seconds=frame * settings.carla.fixed_delta_seconds,
            image_path=relative_image_path,
            control=state["control"],
            location=state["location"],
            rotation=state["rotation"],
            velocity=state["velocity"],
        )
        metadata_writer.append(record)
        saved_frames.append(frame)

    manifest = {
        "mode": "synthetic_cpu",
        "purpose": "local pipeline validation; not a CARLA or SimLingo evaluation",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.machine(),
        "seed": settings.carla.seed,
        "requested_steps": arguments.steps,
        "frame_stride": settings.recording.frame_stride,
    }
    (run_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = validate_outputs(
        run_directory,
        saved_frames,
        settings.recording.image_width,
        settings.recording.image_height,
    )
    (run_directory / "validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("Local CPU pipeline validation passed.")
    print("Frames: {}".format(result["images"]))
    print("Output: {}".format(run_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
