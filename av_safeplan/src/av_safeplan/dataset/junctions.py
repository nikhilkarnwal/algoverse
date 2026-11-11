"""Offline, outcome-blind signalized-site screening; no CARLA dependency.

Trigger locations are NOT junction centers or verified traffic-light identities.
A square envelope is a proposed containment constraint for later road-traced
routes, not proof that sparse XML waypoints follow the roads inside it.
"""

import math
import xml.etree.ElementTree as ET

from av_safeplan.dataset.sources import digest, file_hash

SIGNALIZED_TYPES = {"SignalizedJunctionLeftTurn", "SignalizedJunctionRightTurn"}


def separated(a, b, gap=30.0):
    """Match the dataset splitter's axis-aligned box separation predicate."""
    return (a[2] + gap < b[0] or b[2] + gap < a[0]
            or a[3] + gap < b[1] or b[3] + gap < a[1])


def box(points):
    if not points or any(not all(math.isfinite(float(p[k])) for k in ("x", "y")) for p in points):
        raise ValueError("Missing or non-finite full route geometry")
    return [min(float(p["x"]) for p in points), min(float(p["y"]) for p in points),
            max(float(p["x"]) for p in points), max(float(p["y"]) for p in points)]


def candidates(route_files, town, radius):
    result, inputs = [], []
    for path in sorted(route_files):
        checksum = file_hash(path)
        inputs.append({"path": str(path), "sha256": checksum})
        for route in ET.parse(str(path)).getroot().findall("route"):
            if route.get("town") != town:
                continue
            points = [p.attrib for p in route.findall("./waypoints/position")]
            parent_box = box(points)
            for scenario in route.findall("./scenarios/scenario"):
                kind = scenario.get("type")
                if kind not in SIGNALIZED_TYPES:
                    continue
                trigger = scenario.find("trigger_point")
                if trigger is None:
                    raise ValueError("Signalized scenario lacks a trigger: " + str(path))
                xyz = {key: float(trigger.get(key)) for key in ("x", "y", "z", "yaw")}
                if not all(math.isfinite(v) for v in xyz.values()):
                    raise ValueError("Non-finite trigger")
                x, y = xyz["x"], xyz["y"]
                identity = [checksum, route.get("id"), scenario.get("name"), xyz]
                result.append({"candidate_id": "junction-candidate-" + digest(identity)[:16],
                               "town": town, "source_file": str(path), "source_sha256": checksum,
                               "source_route_id": route.get("id"), "scenario_name": scenario.get("name"),
                               "scenario_type": kind, "trigger": xyz,
                               "proposed_route_envelope_xy": [x-radius, y-radius, x+radius, y+radius],
                               "parent_sparse_route_bounds_xy": parent_box,
                               "carla_junction_id": None, "controlling_signal_ids": [],
                               "signal_association": "unverified", "camera_visibility": "unverified",
                               "road_connectivity": "unverified", "actual_route_geometry": "not_yet_traced"})
    return result, inputs


def screen(items, existing):
    """Cluster overlapping envelopes transitively before choosing any sites."""
    parents = list(range(len(items)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, a in enumerate(items):
        footprint = a["proposed_route_envelope_xy"]
        a["existing_group_conflicts"] = sorted({e["group_id"] for e in existing
            if not separated(footprint, e["bounds_xy"])})
        a["parent_route_conflicts"] = sorted({e["group_id"] for e in existing
            if not separated(a["parent_sparse_route_bounds_xy"], e["bounds_xy"])})
        for j in range(i):
            if not separated(footprint, items[j]["proposed_route_envelope_xy"]):
                parents[root(i)] = root(j)
    groups = {}
    for i, item in enumerate(items):
        groups.setdefault(root(i), []).append(item)
    for members in groups.values():
        group_id = "candidate-cluster-" + digest(sorted(x["candidate_id"] for x in members))[:16]
        conflicts = sorted({g for x in members for g in x["existing_group_conflicts"]})
        for item in members:
            item["candidate_cluster_id"] = group_id
            item["cluster_existing_conflicts"] = conflicts
            item["screening_status"] = "rejected_overlap" if conflicts else "provisional_nonoverlap"
    eligible = sorted((x for x in items if x["screening_status"] == "provisional_nonoverlap"),
                      key=lambda x: x["candidate_id"])
    chosen, used = [], set()
    for item in eligible:
        if item["candidate_cluster_id"] in used:
            continue
        chosen.append(item)
        used.add(item["candidate_cluster_id"])
        if len(chosen) == 2:
            break
    proposals = [{"candidate_id": item["candidate_id"],
                  "candidate_cluster_id": item["candidate_cluster_id"],
                  "proposed_split": "test" if i == 0 else "development",
                  "assignment_status": "proposal_only_not_applied"}
                 for i, item in enumerate(chosen)]
    return sorted(items, key=lambda x: x["candidate_id"]), proposals
