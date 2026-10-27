#!/usr/bin/env python3
"""Build a manual-audit queue of positive, near-miss, and negative episodes."""

import argparse
import json
from pathlib import Path
import random
from typing import Any, Dict, Iterable, List, Mapping, Sequence


POSITIVE_EVENTS = {"collision", "red_light_violation"}
NEAR_MISS_EVENTS = {"near_miss"}


def read_records(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def event_types(record: Mapping[str, Any]) -> List[str]:
    return sorted({str(event.get("event_type")) for event in record.get("events", [])})


def audit_item(
    run_directory: Path,
    records: Sequence[Mapping[str, Any]],
    index: int,
    category: str,
    window_frames: int,
) -> Dict[str, Any]:
    record = records[index]
    first_index = max(0, index - window_frames)
    last_index = min(len(records) - 1, index + window_frames)
    frame = int(record["frame"])
    image_path = run_directory / "rgb" / "frame_{:06d}.png".format(frame)
    return {
        "run_directory": str(run_directory),
        "category": category,
        "center_frame": frame,
        "window_start_frame": int(records[first_index]["frame"]),
        "window_end_frame": int(records[last_index]["frame"]),
        "event_types": event_types(record),
        "image": str(image_path) if image_path.is_file() else None,
        "route_id": record.get("route", {}).get("route_id"),
        "policy": record.get("policy"),
        "scenario": record.get("scenario"),
        "audit": {
            "reviewed": False,
            "label_correct": None,
            "notes": "",
        },
    }


def build_queue(
    episode_paths: Iterable[Path],
    *,
    negatives_per_run: int,
    window_frames: int,
    seed: int,
) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    rng = random.Random(seed)
    for episode_path in sorted(episode_paths):
        records = read_records(episode_path)
        if not records:
            continue
        run_directory = episode_path.parent
        negative_indices = []
        for index, record in enumerate(records):
            labels = set(event_types(record))
            if labels.intersection(POSITIVE_EVENTS):
                queue.append(audit_item(
                    run_directory, records, index, "positive", window_frames
                ))
            elif labels.intersection(NEAR_MISS_EVENTS):
                queue.append(audit_item(
                    run_directory, records, index, "near_miss", window_frames
                ))
            elif not labels:
                negative_indices.append(index)

        rng.shuffle(negative_indices)
        for index in sorted(negative_indices[:negatives_per_run]):
            queue.append(audit_item(
                run_directory, records, index, "negative", window_frames
            ))
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs_root", type=Path)
    parser.add_argument(
        "--episode",
        action="append",
        type=Path,
        default=[],
        help="Use only this episode.jsonl; repeat for a curated review set",
    )
    parser.add_argument("--output", type=Path, default=Path("audit_queue.jsonl"))
    parser.add_argument("--negatives-per-run", type=int, default=3)
    parser.add_argument("--window-frames", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    arguments = parser.parse_args()
    if arguments.negatives_per_run < 0:
        parser.error("--negatives-per-run cannot be negative")
    if arguments.window_frames < 0:
        parser.error("--window-frames cannot be negative")

    episode_paths = (
        [path.expanduser().resolve() for path in arguments.episode]
        if arguments.episode
        else arguments.runs_root.expanduser().resolve().glob("**/episode.jsonl")
    )
    if arguments.episode:
        for path in episode_paths:
            if not path.is_file():
                parser.error("episode does not exist: {}".format(path))
    queue = build_queue(
        episode_paths,
        negatives_per_run=arguments.negatives_per_run,
        window_frames=arguments.window_frames,
        seed=arguments.seed,
    )
    output_path = arguments.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for item in queue:
            stream.write(json.dumps(item, sort_keys=True) + "\n")

    counts = {
        category: sum(item["category"] == category for item in queue)
        for category in ("positive", "near_miss", "negative")
    }
    print(json.dumps({
        "output": str(output_path),
        "items": len(queue),
        "categories": counts,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
