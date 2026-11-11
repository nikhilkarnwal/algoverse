#!/usr/bin/env python3
"""Screen official signalized scenario triggers without simulation or outcomes."""

import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from av_safeplan.dataset.junctions import box, candidates, screen
from av_safeplan.dataset.sources import contained, file_hash, read_json, read_rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--routes", type=Path, action="append", required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--town", default="Town12")
    p.add_argument("--envelope-radius-m", type=float, default=200.)
    args = p.parse_args()
    if not math.isfinite(args.envelope_radius_m) or args.envelope_radius_m < 130:
        p.error("Envelope radius must be finite and at least 130m for the planned route window")
    source = args.source_root.resolve()
    existing = []
    for ep in read_rows(args.dataset / "episodes.jsonl"):
        if not ep.get("map"):
            raise ValueError("Unknown existing map prevents independence screening")
        if ep["map"] != args.town:
            continue
        path = contained(source, source / ep["source"])
        manifest = path.parent / "manifest.json"
        expected = ep["source_hashes"].get("manifest.json")
        if not expected or file_hash(manifest) != expected:
            raise ValueError("Existing manifest changed or missing hash")
        geometry = read_json(manifest).get("route_geometry", [])
        existing.append({"episode_id": ep["episode_id"], "group_id": ep["group_id"],
                         "split": ep["split"], "bounds_xy": box(geometry),
                         "manifest_sha256": expected})
    if not existing:
        raise ValueError("No existing route geometry for the requested town")
    items, inputs = candidates(args.routes, args.town, args.envelope_radius_m)
    items, proposals = screen(items, existing)
    report = {"schema": "av-safeplan-junction-screen-v1", "status": "provisional_requires_map_inspection",
              "town": args.town, "envelope_radius_m": args.envelope_radius_m,
              "separation_gap_m": 30, "selection": "stable candidate-ID order, one per nonoverlapping connected cluster; no outcomes read",
              "input_routes": inputs, "episodes_inventory_sha256": file_hash(args.dataset / "episodes.jsonl"),
              "existing_coverage": existing, "candidates": items, "proposals": proposals,
              "candidate_count": len(items),
              "eligible_cluster_count": len({x["candidate_cluster_id"] for x in items if x["screening_status"] == "provisional_nonoverlap"}),
              "required_before_collection": ["Trace actual short routes on CARLA roads and require containment in proposed envelopes",
                  "Recompute connected groups with all existing and proposed full route geometry",
                  "Resolve actual junction IDs and ego-lane controlling signals/stop lines",
                  "Validate camera visibility and synchronized signal evidence",
                  "Implement or verify explicit test reservation without altering existing assignments"],
              "limitations": ["Official scenario names indicate candidates, not verified signal association",
                  "Trigger is upstream of junction, not its center",
                  "30m is the splitter gap between boxes, not 30m inflation on both sides",
                  "Parent sparse route is NOT the short executable route; no route XML emitted",
                  "No statistical independence or training-readiness claim", "No simulator or collection started"]}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "junction_candidates.json").write_text(json.dumps(report, indent=2) + "\n")
    selected = {x["candidate_id"]: x for x in items}
    lines = ["# Provisional Town12 junction candidates", "", "Offline screening only. Not approved for collection.", "",
             "Scanned {} candidates; {} eligible conservative clusters.".format(len(items), report["eligible_cluster_count"]), "",
             "| Proposed use | Candidate | Scenario | Trigger x, y (m) | Signal / camera |", "|---|---|---|---|---|"]
    for proposal in proposals:
        item = selected[proposal["candidate_id"]]
        lines.append("| {} | {} | {} | {:.1f}, {:.1f} | unverified / unverified |".format(
            proposal["proposed_split"], item["candidate_id"], item["scenario_type"], item["trigger"]["x"], item["trigger"]["y"]))
    lines += ["", "## Required before collection", ""] + ["- " + s for s in report["required_before_collection"]]
    lines += ["", "## Limits", ""] + ["- " + s for s in report["limitations"]]
    (args.output / "junction_candidates.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "candidate_count", "eligible_cluster_count", "proposals")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
