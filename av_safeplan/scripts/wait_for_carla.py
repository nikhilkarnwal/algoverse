#!/usr/bin/env python3
"""Wait until the CARLA RPC API can return a world, not just accept TCP."""

import argparse
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from av_safeplan.environment.checks import apply_python_paths
from av_safeplan.settings import load_stack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stack.yaml")
    arguments = parser.parse_args()

    settings = load_stack(arguments.config)
    apply_python_paths(settings)

    import carla

    deadline = time.monotonic() + settings.carla.startup_timeout_seconds
    last_error = "server has not accepted an RPC request"
    while time.monotonic() < deadline:
        try:
            client = carla.Client(settings.carla.host, settings.carla.port)
            client.set_timeout(min(settings.carla.timeout_seconds, 5.0))
            server_version = client.get_server_version()
            world = client.get_world()
            current_map = world.get_map().name
            print(
                "CARLA RPC is ready: version={}, map={}".format(
                    server_version, current_map
                )
            )
            return 0
        except Exception as error:
            last_error = str(error)
            time.sleep(2.0)

    print(
        "CARLA RPC did not become ready within {:.0f} seconds: {}".format(
            settings.carla.startup_timeout_seconds,
            last_error,
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
