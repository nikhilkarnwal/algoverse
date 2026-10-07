#!/usr/bin/env python3
"""Compare two recorded CARLA runs for deterministic replay drift."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


def load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ValueError("Required file does not exist: {}".format(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object in {}".format(path))
    return value


def load_trajectory(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise ValueError("Required file does not exist: {}".format(path))
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def maximum_axis_delta(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    axes: Iterable[str],
) -> float:
    return max(abs(float(first[axis]) - float(second[axis])) for axis in axes)


def compare_records(
    first_records: List[Dict[str, Any]],
    second_records: List[Dict[str, Any]],
) -> Dict[str, float]:
    maxima = {
        "position": 0.0,
        "rotation": 0.0,
        "velocity": 0.0,
        "control": 0.0,
    }
    for first, second in zip(first_records, second_records):
        maxima["position"] = max(
            maxima["position"],
            maximum_axis_delta(
                first["ego"]["location"],
                second["ego"]["location"],
                ("x", "y", "z"),
            ),
        )
        maxima["rotation"] = max(
            maxima["rotation"],
            maximum_axis_delta(
                first["ego"]["rotation"],
                second["ego"]["rotation"],
                ("pitch", "yaw", "roll"),
            ),
        )
        maxima["velocity"] = max(
            maxima["velocity"],
            maximum_axis_delta(
                first["ego"]["velocity"],
                second["ego"]["velocity"],
                ("x", "y", "z"),
            ),
        )
        maxima["control"] = max(
            maxima["control"],
            maximum_axis_delta(
                first["control"],
                second["control"],
                ("steer", "throttle", "brake"),
            ),
        )
    return maxima


def comparable_configuration(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "seed": manifest.get("seed"),
        "route": manifest.get("route"),
        "simulation": manifest.get("simulation"),
        "policy": manifest.get("policy"),
        "carla": manifest.get("carla"),
        "recording": manifest.get("recording"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_run", type=Path)
    parser.add_argument("second_run", type=Path)
    parser.add_argument("--position-tolerance", type=float, default=0.05)
    parser.add_argument("--rotation-tolerance", type=float, default=0.25)
    parser.add_argument("--velocity-tolerance", type=float, default=0.05)
    parser.add_argument("--control-tolerance", type=float, default=0.01)
    arguments = parser.parse_args()

    first_manifest = load_json(arguments.first_run / "manifest.json")
    second_manifest = load_json(arguments.second_run / "manifest.json")
    run_statuses = (
        first_manifest.get("outcome", {}).get("status"),
        second_manifest.get("outcome", {}).get("status"),
    )
    if run_statuses != ("passed", "passed"):
        print(
            "Both replay manifests must have passed outcomes; found {} and {}.".format(
                run_statuses[0],
                run_statuses[1],
            )
        )
        return 2

    first_configuration = comparable_configuration(first_manifest)
    second_configuration = comparable_configuration(second_manifest)
    if first_configuration != second_configuration:
        print("Replay configurations do not match.")
        print(json.dumps({
            "first": first_configuration,
            "second": second_configuration,
        }, indent=2, sort_keys=True))
        return 2

    first_records = load_trajectory(arguments.first_run / "trajectory.jsonl")
    second_records = load_trajectory(arguments.second_run / "trajectory.jsonl")
    if len(first_records) != len(second_records):
        print(
            "Replay lengths differ: {} records versus {} records.".format(
                len(first_records),
                len(second_records),
            )
        )
        return 2
    if not first_records:
        print("Replay comparison requires recorded trajectory frames.")
        return 2

    maxima = compare_records(first_records, second_records)
    tolerances = {
        "position": arguments.position_tolerance,
        "rotation": arguments.rotation_tolerance,
        "velocity": arguments.velocity_tolerance,
        "control": arguments.control_tolerance,
    }
    failures = {
        name: {"observed": maxima[name], "tolerance": tolerance}
        for name, tolerance in tolerances.items()
        if maxima[name] > tolerance
    }
    result = {
        "status": "pass" if not failures else "fail",
        "compared_records": len(first_records),
        "route_id": first_configuration["route"]["route_id"],
        "maximum_deltas": maxima,
        "tolerances": tolerances,
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
