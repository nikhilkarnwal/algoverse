#!/usr/bin/env python3
"""Check collection integrity separately from official driving success."""

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from av_safeplan.dataset.builder import write_json
from av_safeplan.dataset.sources import file_hash, read_json, read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--route", action="append", required=True, choices=("0", "1", "2"))
    args = parser.parse_args()
    reports = []
    for route in args.route:
        episode = args.run / "telemetry" / ("week2-upstream-" + route)
        reasons, criteria = [], []
        log = args.run / ("route-" + route + ".log")
        text = log.read_text(errors="replace") if log.is_file() else ""
        for marker in ("Skipping scenario", "Traceback", "Could not setup required agent"):
            if marker in text:
                reasons.append(marker)
        exit_file = args.run / ("route-" + route + "-exit_code.txt")
        if not exit_file.is_file() or exit_file.read_text().strip() != "0":
            reasons.append("nonzero_or_missing_process_exit")
        for path in sorted((args.run / "criteria" / ("route-" + route)).glob("*.json")):
            payload = read_json(path)
            if "criteria" in payload:
                criteria.append({"path": str(path.relative_to(args.run)), "sha256": file_hash(path),
                                 "success": payload.get("success"), "criteria": payload["criteria"]})
        if len(criteria) != 1:
            reasons.append("expected_one_official_result")
        counts = {}
        try:
            records = read_rows(episode / "episode.jsonl")
            trajectories = read_rows(episode / "trajectory.jsonl")
            manifest = read_json(episode / "manifest.json")
            counts = {"episode_records": len(records), "trajectory_records": len(trajectories),
                      "images": len(list((episode / "rgb").glob("*.png")))}
            if not records or len(set(counts.values())) != 1:
                reasons.append("empty_or_mismatched_record_counts")
            if any(a["frame"] != b["world_frame"] or b["sensor_frame"] != b["world_frame"] for a, b in zip(records, trajectories)):
                reasons.append("frame_mismatch")
            if manifest.get("outcome", {}).get("status") != "completed":
                reasons.append("recorder_not_completed")
        except (OSError, ValueError, KeyError, TypeError) as error:
            reasons.append(type(error).__name__ + ":" + str(error))
        report = {"route_id": route, "collection_integrity": "pass" if not reasons else "fail",
                  "reasons": reasons, "counts": counts, "official": criteria,
                  "semantic_review": "pending; collection integrity is not label approval"}
        reports.append(report)
    output = args.run / "collection_report.json"
    write_json(output, {"status": "pass" if all(r["collection_integrity"] == "pass" for r in reports) else "fail",
                        "routes": reports})
    print(output.read_text())
    return 0 if all(r["collection_integrity"] == "pass" for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
