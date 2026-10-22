#!/usr/bin/env python3
"""Compare two recorded CARLA runs for deterministic replay drift."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


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


def axis_delta(first: float, second: float, angular: bool = False) -> float:
    if angular:
        return abs((first - second + 180.0) % 360.0 - 180.0)
    return abs(first - second)


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    index = int(fraction * (len(ordered) - 1))
    return float(ordered[index])


def metric_summary(
    first_records: Sequence[Mapping[str, Any]],
    second_records: Sequence[Mapping[str, Any]],
    path: Tuple[str, ...],
    axes: Sequence[str],
    *,
    angular: bool = False,
) -> Dict[str, Any]:
    observations = []
    per_axis: Dict[str, List[float]] = {axis: [] for axis in axes}
    for record_index, (first, second) in enumerate(zip(first_records, second_records)):
        first_value: Mapping[str, Any] = first
        second_value: Mapping[str, Any] = second
        for key in path:
            first_value = first_value[key]
            second_value = second_value[key]
        for axis in axes:
            left = float(first_value[axis])
            right = float(second_value[axis])
            delta = axis_delta(left, right, angular=angular)
            observations.append((delta, record_index, axis, left, right))
            per_axis[axis].append(delta)

    maximum = max(observations, key=lambda item: item[0])
    deltas = [item[0] for item in observations]
    return {
        "maximum": maximum[0],
        "p95": percentile(deltas, 0.95),
        "mean": sum(deltas) / len(deltas),
        "maximum_observation": {
            "record_index": maximum[1],
            "axis": maximum[2],
            "first": maximum[3],
            "second": maximum[4],
        },
        "per_axis": {
            axis: {
                "maximum": max(values),
                "p95": percentile(values, 0.95),
                "mean": sum(values) / len(values),
            }
            for axis, values in per_axis.items()
        },
    }


def compare_records(
    first_records: List[Dict[str, Any]],
    second_records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return {
        "position": metric_summary(
            first_records, second_records, ("ego", "location"), ("x", "y", "z")
        ),
        "rotation": metric_summary(
            first_records,
            second_records,
            ("ego", "rotation"),
            ("pitch", "yaw", "roll"),
            angular=True,
        ),
        "velocity": metric_summary(
            first_records, second_records, ("ego", "velocity"), ("x", "y", "z")
        ),
        "control": metric_summary(
            first_records,
            second_records,
            ("control",),
            ("steer", "throttle", "brake"),
        ),
    }


def comparable_configuration(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "seed": manifest.get("seed"),
        "route": manifest.get("route"),
        "simulation": manifest.get("simulation"),
        "policy": manifest.get("policy"),
        "carla": manifest.get("carla"),
        "recording": manifest.get("recording"),
        "scenario": manifest.get("scenario"),
        "initialization": manifest.get("initialization"),
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

    metrics = compare_records(first_records, second_records)
    maxima = {name: summary["maximum"] for name, summary in metrics.items()}
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
        "metrics": metrics,
        "tolerances": tolerances,
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
