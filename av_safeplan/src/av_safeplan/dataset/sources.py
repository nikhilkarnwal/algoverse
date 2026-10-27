"""Strict readers and portable, content-addressed source inventory."""

import hashlib
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def contained(root, path):
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def read_json(path):
    def invalid(value):
        raise ValueError("non-finite JSON constant: " + value)
    with path.open(encoding="utf-8") as stream:
        result = json.load(stream, parse_constant=invalid)
    validate_numbers(result)
    return result


def validate_numbers(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric value")
    if isinstance(value, dict):
        for child in value.values():
            validate_numbers(child)
    elif isinstance(value, list):
        for child in value:
            validate_numbers(child)


def read_rows(path):
    def invalid(value):
        raise ValueError("non-finite JSON constant: " + value)
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line, parse_constant=invalid)
                    if not isinstance(row, dict):
                        raise ValueError("expected object")
                    validate_numbers(row)
                    rows.append(row)
                except ValueError as error:
                    raise ValueError("{} line {}: {}".format(path.name, number, error))
    return rows


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def valid_action(action):
    if not isinstance(action, dict):
        return False
    return (all(finite(action.get(k)) and low <= action[k] <= high
                for k, low, high in (("steer", -1, 1), ("throttle", 0, 1), ("brake", 0, 1)))
            and all(isinstance(action.get(k), bool) for k in ("hand_brake", "reverse")))


def load_episode(root, path):
    path = contained(root, path)
    rows = read_rows(path)
    if not rows:
        raise ValueError("empty_episode")
    previous = None
    for row in rows:
        frame, stamp = row.get("frame"), row.get("timestamp_seconds")
        if not isinstance(frame, int) or isinstance(frame, bool) or not finite(stamp):
            raise ValueError("invalid_frame_or_timestamp")
        if previous and (frame <= previous[0] or stamp <= previous[1]):
            raise ValueError("nonmonotonic_or_duplicate_frame")
        if not valid_action(row.get("base_policy_action")) or not valid_action(row.get("safety_supervisor_action")):
            raise ValueError("invalid_control")
        if not isinstance(row.get("supervisor_intervened"), bool):
            raise ValueError("missing_intervention_state")
        if not isinstance(row.get("events"), list):
            raise ValueError("missing_events")
        for event in row["events"]:
            if (not isinstance(event, dict) or not isinstance(event.get("event_type"), str)
                    or type(event.get("frame")) is not int or not isinstance(event.get("details", {}), dict)):
                raise ValueError("malformed_event")
        if not isinstance(row.get("ego"), dict) or not isinstance(row.get("route"), dict):
            raise ValueError("missing_ego_or_route")
        previous = (frame, stamp)
    files = {"episode.jsonl": file_hash(path)}
    manifest = {}
    finalization = None
    trajectories = {}
    for name in ("manifest.json", "trajectory.jsonl", "dataset_review.json", "finalization.json"):
        p = contained(root, path.parent / name)
        if p.is_file():
            files[name] = file_hash(p)
            if name == "manifest.json":
                manifest = read_json(p)
                if not isinstance(manifest, dict):
                    raise ValueError("invalid_manifest")
            elif name == "finalization.json":
                finalization = read_json(p)
            elif name == "trajectory.jsonl":
                for record in read_rows(p):
                    frame = record.get("world_frame")
                    if not isinstance(frame, int) or frame in trajectories:
                        raise ValueError("invalid_or_duplicate_trajectory_frame")
                    trajectories[frame] = record
    policies = {row.get("policy") for row in rows}
    if len(policies) != 1:
        raise ValueError("policy_changed_within_episode")
    policy = next(iter(policies))
    backend = manifest.get("backend") or (rows[0].get("scenario") or {}).get("backend", "legacy")
    mapping = manifest.get("route") or rows[0].get("route") or {}
    map_name = manifest.get("map") or mapping.get("map") or mapping.get("map_name")
    route_id = mapping.get("route_id") or manifest.get("route_id") or ""
    if not map_name and "Town" in route_id:
        map_name = route_id.split(":")[0].split("/")[-1]
    if map_name:
        map_name = str(map_name).split("/")[-1]
    official = None
    report_path = path.parent.parent.parent / "collection_report.json"
    if root.resolve() in report_path.resolve().parents and report_path.is_file():
        report = read_json(contained(root, report_path))
        for item in report.get("routes", []):
            if path.parent.name == "week2-upstream-" + str(item.get("route_id")):
                official = item
                files["../../collection_report.json"] = file_hash(report_path)
                break
    if backend == "leaderboard":
        result_path = path.parent.parent.parent / "simulation_results.json"
        if root.resolve() in result_path.resolve().parents and result_path.is_file():
            result = read_json(contained(root, result_path))
            files["../../simulation_results.json"] = file_hash(result_path)
            records = result.get("_checkpoint", {}).get("records", [])
            selected = str(mapping.get("selected_route_ids", ""))
            # Current wrapper only identifies a route subset, not a repetition.
            # Never attach one aggregate result to several telemetry episodes.
            episodes_here = list(path.parent.parent.glob("*/episode.jsonl"))
            exact = (len(records) == 1 and len(episodes_here) == 1
                     and records[0].get("route_id") == "RouteScenario_" + selected + "_rep0")
            complete = (exact and result.get("entry_status") == "Finished"
                        and result.get("_checkpoint", {}).get("progress") == [1, 1]
                        and records[0].get("scores", {}).get("score_route") == 100
                        and manifest.get("outcome", {}).get("status") == "closed")
            official = {"source": "leaderboard_simulation_results", "scope": "episode_aggregate_only",
                        "collection_integrity": "pass" if complete else "unverified",
                        "entry_status": result.get("entry_status"),
                        "record": records[0] if exact else None,
                        "association": "single_episode_single_route_rep0" if exact else "ambiguous"}
    route_xml = path.parent.parent.parent / "routes.xml"
    if root.resolve() in route_xml.resolve().parents and route_xml.is_file():
        files["../../routes.xml"] = file_hash(contained(root, route_xml))
    delta = manifest.get("fixed_delta_seconds")
    if not finite(delta) or delta <= 0:
        deltas = [(b["timestamp_seconds"] - a["timestamp_seconds"]) / (b["frame"] - a["frame"])
                  for a, b in zip(rows, rows[1:])]
        delta = sorted(deltas)[len(deltas) // 2] if deltas else None
    gaps = []
    for a, b in zip(rows, rows[1:]):
        if b["frame"] != a["frame"] + 1 or delta is None or abs(b["timestamp_seconds"] - a["timestamp_seconds"] - delta) > max(1e-5, delta * 0.02):
            gaps.append((a["timestamp_seconds"], b["timestamp_seconds"]))
    review_path = path.parent / "dataset_review.json"
    review = read_json(review_path) if review_path.is_file() else {}
    if not isinstance(review, dict):
        raise ValueError("invalid_review")
    # Reviews bind to the exact raw episode, not a mutable folder name.
    if review and review.get("episode_sha256") != files["episode.jsonl"]:
        raise ValueError("stale_review_hash")
    if not isinstance(review.get("intervals", []), list):
        raise ValueError("invalid_review_intervals")
    for interval in review.get("intervals", []):
        if (not isinstance(interval, dict)
                or interval.get("hazard") not in ("collision", "red_light_violation")
                or type(interval.get("value")) is not int or interval["value"] not in (0, 1)
                or type(interval.get("start_frame")) is not int
                or type(interval.get("end_frame")) is not int
                or interval["start_frame"] > interval["end_frame"]):
            raise ValueError("invalid_review_interval")
    return {"id": "ep-" + files["episode.jsonl"][:24], "path": path,
            "relative": str(path.relative_to(root)), "rows": rows,
            "manifest": manifest, "trajectory": trajectories, "files": files,
            "policy": policy, "backend": backend, "map": map_name,
            "delta": delta, "gaps": gaps, "review": review,
            "geometry": manifest.get("route_geometry", []), "route_id": route_id, "official": official,
            "finalization": finalization}
