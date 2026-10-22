#!/usr/bin/env python3
"""Report objective completion gates for an AV SafePlan Week 1 run."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


REQUIRED_SCENARIOS: Tuple[str, ...] = (
    "lead_brake",
    "cross_traffic",
    "red_light_compliance",
)
AUDIT_CATEGORIES: Tuple[str, ...] = ("positive", "near_miss", "negative")


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_json_lines(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    values: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def passed_manifest(path: Path) -> bool:
    manifest = load_json(path)
    return bool(manifest and manifest.get("outcome", {}).get("status") == "passed")


def scenario_name(manifest: Mapping[str, Any]) -> Optional[str]:
    scenario = manifest.get("scenario")
    if isinstance(scenario, Mapping):
        name = scenario.get("name")
        return str(name) if name else None
    return None


def semantically_validated(manifest: Mapping[str, Any]) -> bool:
    """Require evidence that the intended event occurred, not only process success."""
    validation = manifest.get("validation")
    if not isinstance(validation, Mapping):
        return False
    return str(validation.get("status", "")).strip().lower() == "pass"


def find_scenario_results(session_root: Path) -> Dict[str, bool]:
    found = {name: False for name in REQUIRED_SCENARIOS}
    for path in session_root.glob("**/manifest.json"):
        manifest = load_json(path)
        if not manifest or manifest.get("outcome", {}).get("status") not in {
            "completed",
            "passed",
        }:
            continue
        if not semantically_validated(manifest):
            continue
        name = scenario_name(manifest)
        if name in found:
            found[name] = True
    return found


def audit_result(items: Iterable[Mapping[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    present = {category: 0 for category in AUDIT_CATEGORIES}
    approved = {category: 0 for category in AUDIT_CATEGORIES}
    for item in items:
        category = item.get("category")
        if category not in present:
            continue
        present[str(category)] += 1
        audit = item.get("audit", {})
        if (
            isinstance(audit, Mapping)
            and audit.get("reviewed") is True
            and audit.get("label_correct") is True
        ):
            approved[str(category)] += 1
    return present, approved


def simlingo_passed(path: Path) -> bool:
    result = load_json(path)
    if not result:
        return False
    failure_words = {"failed", "failure", "crashed", "error", "rejected"}
    success_words = {"completed", "complete", "finished", "success", "succeeded"}

    statuses: List[str] = []
    for key in ("status", "entry_status"):
        value = result.get(key)
        if value is not None:
            statuses.append(str(value).strip().lower())

    checkpoint = result.get("_checkpoint")
    if isinstance(checkpoint, Mapping):
        progress = checkpoint.get("progress")
        if (
            isinstance(progress, list)
            and len(progress) == 2
            and all(isinstance(value, (int, float)) for value in progress)
        ):
            if progress[1] <= 0 or progress[0] < progress[1]:
                return False
        records = checkpoint.get("records")
        if isinstance(records, list) and records:
            for record in records:
                if not isinstance(record, Mapping):
                    return False
                record_status = str(record.get("status", "")).strip().lower()
                if record_status:
                    statuses.append(record_status)

    if any(any(word in status for word in failure_words) for status in statuses):
        return False
    return any(any(word in status for word in success_words) for status in statuses)


def gate(status: bool, details: Any) -> Dict[str, Any]:
    return {"status": "pass" if status else "pending", "details": details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_root", type=Path)
    parser.add_argument(
        "--simlingo-results",
        type=Path,
        default=None,
        help="Leaderboard simulation_results.json for the frozen SimLingo run",
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Write the report but return success while completion gates are pending",
    )
    arguments = parser.parse_args()

    session_root = arguments.session_root.expanduser().resolve()
    if not session_root.is_dir():
        parser.error("session root does not exist: {}".format(session_root))

    replay_comparison = load_json(session_root / "replay_comparison.json") or {}
    scenario_results = find_scenario_results(session_root)
    audit_items = load_json_lines(session_root / "audit_queue.jsonl")
    audit_present, audit_approved = audit_result(audit_items)
    simlingo_path = (
        arguments.simlingo_results.expanduser().resolve()
        if arguments.simlingo_results is not None
        else session_root / "simlingo" / "simulation_results.json"
    )

    gates = {
        "town12_smoke": gate(
            passed_manifest(session_root / "town12-smoke" / "manifest.json"),
            str(session_root / "town12-smoke" / "manifest.json"),
        ),
        "deterministic_replay": gate(
            replay_comparison.get("status") == "pass",
            replay_comparison or "replay_comparison.json is missing or invalid",
        ),
        "controlled_scenarios": gate(
            all(scenario_results.values()),
            scenario_results,
        ),
        "audit_queue_coverage": gate(
            all(audit_present[category] > 0 for category in AUDIT_CATEGORIES),
            audit_present,
        ),
        "manual_label_audit": gate(
            all(audit_approved[category] > 0 for category in AUDIT_CATEGORIES),
            {
                "approved": audit_approved,
                "requirement": "At least one reviewed, correct label in each category.",
            },
        ),
        "simlingo_closed_loop": gate(
            simlingo_passed(simlingo_path),
            str(simlingo_path),
        ),
    }
    complete = all(item["status"] == "pass" for item in gates.values())
    report = {
        "status": "complete" if complete else "pending",
        "session_root": str(session_root),
        "gates": gates,
    }
    output_path = session_root / "week1_status.json"
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print("Week 1 report: {}".format(output_path))
    if complete or arguments.allow_pending:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
