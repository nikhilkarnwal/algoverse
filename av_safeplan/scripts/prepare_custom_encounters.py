#!/usr/bin/env python3
"""Write six custom TRAIN-only route definitions; never start CARLA or collect data."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from av_safeplan.scenarios.custom_catalog import load_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "config/custom_encounters.json")
    parser.add_argument("--town", required=True)
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--z", type=float, required=True)
    parser.add_argument("--yaw", type=float, required=True)
    parser.add_argument("--training-location-id", required=True,
                        help="Previously reserved training location; all six variants share this group")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not all(math.isfinite(v) for v in (args.x, args.y, args.z, args.yaw)):
        parser.error("Anchor coordinates must be finite")
    catalog = load_catalog(args.catalog)
    length = catalog["first_encounter_m"] + (catalog["encounters_per_route"]-1)*catalog["spacing_m"] + 45
    args.output_dir.mkdir(parents=True, exist_ok=False)
    catalog_bytes = args.catalog.read_bytes()
    (args.output_dir / "catalog.json").write_bytes(catalog_bytes)
    entries = []
    for name in catalog["cases"]:
        root = ET.Element("routes")
        route = ET.SubElement(root, "route", id=name, town=args.town)
        weather = ET.SubElement(route, "weathers")
        ET.SubElement(weather, "weather", route_percentage="0", cloudiness="0", precipitation="0", sun_altitude_angle="60")
        points = ET.SubElement(route, "waypoints")
        for distance in range(0, int(length)+1, 5):
            ET.SubElement(points, "position", x=str(args.x+distance*math.cos(math.radians(args.yaw))),
                          y=str(args.y+distance*math.sin(math.radians(args.yaw))), z=str(args.z))
        scenarios = ET.SubElement(route, "scenarios")
        scenario = ET.SubElement(scenarios, "scenario", name=name, type="AVSafePlanRepeatedEncounters")
        ET.SubElement(scenario, "trigger_point", x=str(args.x), y=str(args.y), z=str(args.z), yaw=str(args.yaw))
        ET.SubElement(scenario, "case", value=name)
        path = args.output_dir / (name + ".xml")
        ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
        entries.append(dict(case=name, route_file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            group_id=args.training_location_id, split="train", seed=args.seed))
    manifest = dict(schema_version=1, provenance="custom_not_official", routes=entries,
                    catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
                    geometry_status="requires_live_preflight", split_exclusion_status="requires_location_audit",
                    review="deferred", loss_mask=False, training_eligible=False,
                    note="No runs started. On collision stop; remaining encounters require a separately approved fresh episode.")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print("Prepared six custom route definitions; live geometry and split-exclusion checks still required.")


if __name__ == "__main__":
    main()
