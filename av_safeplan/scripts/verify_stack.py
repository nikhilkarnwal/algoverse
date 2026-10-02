#!/usr/bin/env python3
"""Validate the pinned AV SafePlan runtime without modifying the machine."""

import argparse
import json
from pathlib import Path
import sys
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.environment.checks import CheckResult, apply_python_paths, run_offline_checks
from av_safeplan.settings import load_stack


def live_checks(settings) -> List[CheckResult]:
    apply_python_paths(settings)
    try:
        import carla

        client = carla.Client(settings.carla.host, settings.carla.port)
        client.set_timeout(settings.carla.timeout_seconds)
        client_version = client.get_client_version()
        server_version = client.get_server_version()
        maps = client.get_available_maps()
        town_available = any(item.endswith("/{}".format(settings.carla.map_name)) for item in maps)
        return [
            CheckResult(
                "carla_client_server_version",
                "pass" if client_version == server_version == settings.carla.version else "fail",
                "expected {}, client {}, server {}".format(
                    settings.carla.version, client_version, server_version
                ),
            ),
            CheckResult(
                "carla_map_{}".format(settings.carla.map_name),
                "pass" if town_available else "fail",
                "available" if town_available else "not returned by CARLA server",
            ),
        ]
    except Exception as error:
        return [CheckResult("carla_live_connection", "fail", str(error))]


def render(results: List[CheckResult]) -> None:
    width = max(len(result.name) for result in results)
    for result in results:
        print("{:<{width}}  {:<4}  {}".format(
            result.name, result.status.upper(), result.detail, width=width
        ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    parser.add_argument("--live", action="store_true", help="Connect to a running CARLA server")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    arguments = parser.parse_args()

    settings = load_stack(arguments.config)
    results = run_offline_checks(settings)
    if arguments.live:
        results.extend(live_checks(settings))

    if arguments.json:
        print(json.dumps([result.to_dict() for result in results], indent=2))
    else:
        render(results)
    return 1 if any(result.required and result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
