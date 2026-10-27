#!/usr/bin/env python3
"""Attach reviewed ScenarioRunner criteria to an AV SafePlan run manifest."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict


FAMILIES = ("lead_brake", "cross_traffic", "red_light_compliance")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--criteria", type=Path, required=True)
    parser.add_argument("--status", choices=("pass", "fail"), required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument(
        "--visual-reviewed",
        action="store_true",
        help="Confirm that saved frames show the intended route/scenario geometry",
    )
    arguments = parser.parse_args()

    manifest_path = arguments.manifest.expanduser().resolve()
    criteria_path = arguments.criteria.expanduser().resolve()
    if not manifest_path.is_file():
        parser.error("manifest does not exist: {}".format(manifest_path))
    if not criteria_path.is_file():
        parser.error("criteria JSON does not exist: {}".format(criteria_path))
    if arguments.status == "pass" and not arguments.visual_reviewed:
        parser.error("--visual-reviewed is required when recording a pass")

    manifest = _load_json(manifest_path)
    criteria = _load_json(criteria_path)
    criteria_status = _find_result_status(criteria)
    manifest["scenario"] = {
        "name": arguments.family,
        "backend": "scenario_runner",
    }
    manifest["validation"] = {
        "status": arguments.status,
        "source": "scenario_runner_criteria_and_visual_review",
        "criteria_file": str(criteria_path),
        "criteria_sha256": hashlib.sha256(criteria_path.read_bytes()).hexdigest(),
        "criteria_reported_status": criteria_status,
        "visual_reviewed": bool(arguments.visual_reviewed),
        "review_note": arguments.note,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["validation"], indent=2, sort_keys=True))
    return 0


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit("invalid JSON at {}: {}".format(path, error))
    if not isinstance(value, dict):
        raise SystemExit("expected a JSON object at {}".format(path))
    return value


def _find_result_status(value: Any) -> str:
    """Capture an upstream status for audit context without deciding the pass."""
    if isinstance(value, dict):
        if isinstance(value.get("success"), bool):
            return "success" if value["success"] else "failure"
        for key in ("status", "result", "entry_status"):
            if key in value and not isinstance(value[key], (dict, list)):
                return str(value[key])
        for nested in value.values():
            found = _find_result_status(nested)
            if found != "not_found":
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_result_status(nested)
            if found != "not_found":
                return found
    return "not_found"


if __name__ == "__main__":
    raise SystemExit(main())
