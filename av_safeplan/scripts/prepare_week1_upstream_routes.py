#!/usr/bin/env python3
"""Build a small Town12 route set from public Leaderboard route XML files."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from av_safeplan.scenarios.upstream import (
    discover_candidates,
    find_route_files,
    load_upstream_config,
    select_week1_candidates,
    write_reduced_routes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "routes",
        nargs="+",
        type=Path,
        help="Public route XML file(s), or directories containing XML files",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/upstream_scenarios.yaml"),
    )
    parser.add_argument(
        "--output-routes",
        type=Path,
        default=Path("outputs/upstream/week1_town12_routes.xml"),
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("outputs/upstream/week1_town12_selection.json"),
    )
    arguments = parser.parse_args()

    config = load_upstream_config(arguments.config.expanduser().resolve())
    route_files = find_route_files(arguments.routes)
    if not route_files:
        parser.error("no route XML files were found")

    candidates = discover_candidates(route_files, config.town)
    selections, missing = select_week1_candidates(config, candidates)
    if selections:
        write_reduced_routes(selections, arguments.output_routes.expanduser().resolve())

    scenario_counts: Dict[str, int] = {}
    for candidate in candidates:
        if candidate.scenario_type:
            scenario_counts[candidate.scenario_type] = (
                scenario_counts.get(candidate.scenario_type, 0) + 1
            )
    report: Dict[str, Any] = {
        "status": "ready" if not missing else "incomplete",
        "town": config.town,
        "route_files_scanned": [str(path) for path in route_files],
        "town_routes_found": len([
            candidate for candidate in candidates if candidate.scenario_index is None
        ]),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "selections": [
            {"prepared_route_id": str(index), **selection.to_dict()}
            for index, selection in enumerate(selections)
        ],
        "missing_families": missing,
        "live_validation_required": [
            selection.family.name
            for selection in selections
            if selection.family.requires_live_validation
        ],
        "output_routes": str(arguments.output_routes.expanduser().resolve()),
    }
    output_report = arguments.output_report.expanduser().resolve()
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
