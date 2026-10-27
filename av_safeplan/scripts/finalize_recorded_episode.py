#!/usr/bin/env python3
"""Preserve an external exit record and recover video after evaluator shutdown."""

import argparse
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from av_safeplan.dataset.builder import write_json
from av_safeplan.dataset.sources import contained, read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("--process-exit", type=int, required=True)
    parser.add_argument("--recover-video", action="store_true")
    args = parser.parse_args()
    episode = args.episode.resolve()
    rows = read_rows(episode / "episode.jsonl")
    trajectory = read_rows(episode / "trajectory.jsonl")
    frames = {r["frame"] for r in rows}
    recorded = [r for r in trajectory if r["world_frame"] in frames]
    payload = {"process_exit_code": args.process_exit, "episode_records": len(rows),
               "trajectory_records": len(trajectory), "recorded_image_references": len(recorded),
               "outcome": "interrupted" if args.process_exit else "process_exited",
               "note": "Does not assert route completion; inspect official results. Raw files are preserved."}
    payload["video_recovery_status"] = "not_completed" if args.recover_video else "not_requested"
    write_json(episode / "finalization.json", payload)
    if args.recover_video and recorded:
        import cv2
        original = cv2.VideoCapture(str(episode / "trajectory.mp4"))
        original_valid = original.isOpened() and int(original.get(cv2.CAP_PROP_FRAME_COUNT)) == len(recorded)
        original.release()
        if original_valid:
            payload["video"] = "trajectory.mp4"
            payload["video_recovery_status"] = "original_video_valid"
        else:
            output = episode / "recovered-review.mp4"
            if output.exists():
                raise ValueError("Recovery output already exists; raw evidence will not be overwritten")
            deltas = [b["timestamp_seconds"] - a["timestamp_seconds"] for a, b in zip(recorded, recorded[1:])]
            if not deltas or min(deltas) <= 0 or max(deltas) - min(deltas) > 1e-5:
                raise ValueError("Cannot infer constant video timing; use image sequence for review")
            fps = 1. / deltas[0]
            first = cv2.imread(str(contained(episode, episode / recorded[0]["image"])))
            if first is None:
                raise ValueError("First image is unreadable")
            height, width = first.shape[:2]
            writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
            if not writer.isOpened():
                raise RuntimeError("Could not initialize recovery video encoder")
            try:
                for row in recorded:
                    image = cv2.imread(str(contained(episode, episode / row["image"])))
                    if image is None or image.shape[:2] != (height, width):
                        raise ValueError("Missing/inconsistent recovery image")
                    writer.write(image)
            finally:
                writer.release()
            check = cv2.VideoCapture(str(output))
            count = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
            check.release()
            if count != len(recorded):
                raise RuntimeError("Recovered video frame count differs from logged records")
            payload.update(video="recovered-review.mp4", video_frames=count, video_fps=fps,
                           video_recovery_status="recovered",
                           video_recovered_from="only frame references with completed episode records")
    write_json(episode / "finalization.json", payload)
    print(payload)


if __name__ == "__main__":
    main()
