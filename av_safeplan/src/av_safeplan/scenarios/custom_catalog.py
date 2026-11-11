"""Offline, dependency-free validation of custom training encounter recipes."""

import json
import math
from pathlib import Path


def load_catalog(path):
    catalog = json.loads(Path(path).read_text())
    if catalog.get("version") != 1 or catalog.get("split") != "train":
        raise ValueError("Custom encounters require schema 1 and train-only split")
    allowed = (1,) if catalog.get("purpose") == "single_encounter_pilot" else (3, 4, 5)
    if catalog.get("encounters_per_route") not in allowed:
        raise ValueError("Use 3–5 encounters, or explicitly select a single_encounter_pilot")
    bounds = {"first_encounter_m": (40, 80), "spacing_m": (100, 200),
              "stabilization_seconds": (2, 10), "encounter_timeout_seconds": (10, 120)}
    for key, (low, high) in bounds.items():
        _bounded(catalog[key], low, high, key)
    families = {"lead_brake": {"lead_speed_mps": (2, 12), "trigger_gap_m": (8, 35), "brake": (0.1, 1)},
                "pedestrian": {"crossing_speed_mps": (0.5, 3), "trigger_distance_m": (10, 35)},
                "static_obstacle": {"passing_space_m": (2.5, 4)}}
    counts = dict.fromkeys(families, 0)
    for name, case in catalog["cases"].items():
        if not name.replace("_", "").isalnum():
            raise ValueError("Unsafe case name")
        family = case["family"]
        if family not in families or set(case) != {"family"} | set(families[family]):
            raise ValueError("Unknown family or parameters: " + name)
        counts[family] += 1
        for key, (low, high) in families[family].items():
            _bounded(case[key], low, high, key)
    if list(counts.values()) != [2, 2, 2]:
        raise ValueError("Exactly two configurations per family are required")
    return catalog


def _bounded(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Invalid {}: expected {}..{}".format(name, low, high))
