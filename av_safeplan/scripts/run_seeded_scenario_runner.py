#!/usr/bin/env python3
"""Seed the pinned ScenarioRunner process before constructing route actors."""

import os
from pathlib import Path
import random
import runpy
import sys

import numpy as np

root = Path(os.environ["SCENARIO_RUNNER_ROOT"]).resolve()
sys.path.insert(0, str(root))
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider

seed = int(os.environ.get("AV_SAFEPLAN_SCENARIO_SEED", "2026"))
random.seed(seed)
np.random.seed(seed)
# These fields belong to pinned ScenarioRunner v0.9.15; fail on API changes.
if not hasattr(CarlaDataProvider, "_random_seed") or not hasattr(CarlaDataProvider, "_rng"):
    raise RuntimeError("Pinned ScenarioRunner seed hooks are unavailable")
CarlaDataProvider._random_seed = seed
CarlaDataProvider._rng = np.random.RandomState(seed)
os.environ["AV_SAFEPLAN_PROCESS_SEED_APPLIED"] = "1"
sys.argv[0] = str(root / "scenario_runner.py")
runpy.run_path(sys.argv[0], run_name="__main__")
