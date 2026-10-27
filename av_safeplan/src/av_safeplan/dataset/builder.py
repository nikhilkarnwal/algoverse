"""Build auditable samples and collection priorities without loading CARLA."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import subprocess

from av_safeplan.dataset import SCHEMA_VERSION
from av_safeplan.dataset.labels import HAZARDS, extract_evidence, target
from av_safeplan.dataset.sources import contained, digest, file_hash, finite, load_episode, read_json
from av_safeplan.dataset.splits import assign


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_row(stream, payload):
    stream.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")


def code_provenance(project):
    def git(*args):
        p = subprocess.run(["git", "-C", str(project)] + list(args), capture_output=True)
        return p.stdout if p.returncode == 0 else b"unavailable"
    # Include untracked implementation files, not just tracked Git diff.
    paths = list((project / "src" / "av_safeplan" / "dataset").glob("*.py"))
    paths.append(project / "scripts" / "build_week2_dataset.py")
    return {"revision": git("rev-parse", "HEAD").decode().strip(),
            "dirty_diff_sha256": digest(git("diff", "HEAD").decode(errors="replace")),
            "converter_files": {str(p.relative_to(project)): file_hash(p) for p in sorted(paths) if p.is_file()}}


def image_input(root, episode, row):
    record = episode["trajectory"].get(row["frame"])
    reasons = []
    image = None
    if not record or not record.get("image") or record["image"] == ".":
        return None, "invalid", ["missing_image_reference"]
    if record.get("sensor_frame") != row["frame"]:
        reasons.append("sensor_frame_mismatch")
    if not finite(record.get("timestamp_seconds")) or abs(record["timestamp_seconds"] - row["timestamp_seconds"]) > 1e-5:
        reasons.append("trajectory_timestamp_mismatch")
    if record.get("control") != row["safety_supervisor_action"]:
        reasons.append("trajectory_control_mismatch")
    try:
        path = contained(root, contained(episode["path"].parent, episode["path"].parent / record["image"]))
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError("invalid_png_header")
        width, height = struct.unpack(">II", header[16:24])
        if not width or not height:
            raise ValueError("invalid_png_dimensions")
        image = {"path": str(path.relative_to(root)), "sha256": file_hash(path),
                 "width": width, "height": height, "format": "PNG", "channels": "RGB",
                 "preprocessing": "none; decode RGB without resizing; fit any later transforms on train only"}
    except (OSError, ValueError, TypeError) as error:
        reasons.append("missing_or_invalid_image:" + type(error).__name__)
    if reasons:
        return image, "invalid", reasons
    timing = episode["manifest"].get("sensor_timing", {})
    verified = timing.get("source") == "sensor_callback_frame" and timing.get("camera") in ("Center", "rgb_0")
    if not verified:
        reasons.append("camera_alignment_unverified")
    return image, "verified" if verified else "unverified", reasons


def build(root, output, project, horizon=3., stride=.2, seed=2026,
          include=(), previous_splits=None, negative_keep=1.):
    provenance = code_provenance(Path(project))
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError("source root does not exist")
    if not finite(horizon) or horizon <= 0 or not finite(stride) or stride <= 0:
        raise ValueError("horizon and stride must be finite and positive")
    if not finite(negative_keep) or not 0 < negative_keep <= 1:
        raise ValueError("negative_keep must be in (0, 1]")
    # Derived data must never contaminate recursive source discovery.
    if output == root or root in output.parents:
        raise ValueError("output must be outside source root")
    if output.exists():
        raise ValueError("output already exists; use a new version directory")
    paths = sorted({contained(root, root / p) for p in include}) if include else sorted(root.rglob("episode.jsonl"))
    episodes, failures, duplicates, seen = [], [], [], {}
    for path in paths:
        try:
            ep = load_episode(root, path)
            if ep["id"] in seen:
                duplicates.append({"source": str(path.relative_to(root)), "same_as": seen[ep["id"]]})
                continue
            seen[ep["id"]] = ep["relative"]
            episodes.append({k: ep[k] for k in ("id", "path", "relative", "files", "map", "geometry")})
        except (OSError, ValueError, TypeError, KeyError) as error:
            failures.append({"source": str(path.relative_to(root)), "reason": str(error)})
    if not episodes:
        raise ValueError("No readable episodes: " + json.dumps(failures[:5]))
    splits = assign(episodes, seed, read_json(Path(previous_splits)) if previous_splits else None)
    output.mkdir(parents=True, exist_ok=False)
    counts, reasons, labels, policies, strata = Counter(), Counter(), Counter(), Counter(), Counter()
    hazard_counts, event_counts, episode_outcomes = Counter(), Counter(), Counter()
    inventory = []
    (output / "review_templates").mkdir()
    with (output / "samples.jsonl").open("w") as samples, (output / "evidence.jsonl").open("w") as evidence_stream, (output / "episodes.jsonl").open("w") as ep_stream, (output / "review_queue.jsonl").open("w") as review_stream:
        for descriptor in episodes:
            ep = load_episode(root, descriptor["path"])
            if ep["files"] != descriptor["files"]:
                raise ValueError("Source changed during build: " + ep["relative"])
            events, event_errors = extract_evidence(ep)
            for event in events:
                write_row(evidence_stream, event)
                event_counts[event["event_type"] or "unknown"] += 1
            assignment = splits["assignments"][ep["id"]]
            paths_seen = set()
            for record in ep["trajectory"].values():
                if record.get("image") and record["image"] != ".":
                    paths_seen.add(record["image"])
            actual_png = {str(p.relative_to(ep["path"].parent)) for p in (ep["path"].parent / "rgb").glob("*.png")}
            orphan_images = len(actual_png - paths_seen)
            summary = {"episode_id": ep["id"], "source": ep["relative"], "source_hashes": ep["files"],
                       "backend": ep["backend"], "policy": ep["policy"], "map": ep["map"],
                       "route_id": ep["route_id"], "scenario": ep["manifest"].get("scenario", ep["rows"][0].get("scenario")),
                       "seed": ep["rows"][0].get("seed"), "records": len(ep["rows"]),
                       "fixed_delta_seconds": ep["delta"], "timing_source": "manifest_or_verified_frame_time_slope",
                       "gaps": ep["gaps"], "orphan_images": orphan_images,
                       "recorder_outcome": ep["manifest"].get("outcome"),
                       "external_finalization": ep["finalization"],
                       "official_validation": ep["manifest"].get("validation"),
                       "official_collection_evidence": ep["official"],
                       "seed_application": ep["manifest"].get("seed_application", {"status": "not_recorded"}),
                       "event_errors": event_errors, **assignment}
            write_row(ep_stream, summary)
            episode_outcomes[(ep["manifest"].get("outcome") or {}).get("status", "unknown")] += 1
            write_json(output / "review_templates" / (ep["id"] + ".json"), {
                "episode_sha256": ep["files"]["episode.jsonl"], "source": ep["relative"],
                "instructions": "After human review, add hazard/value/start_frame/end_frame/reviewed/label_correct/reviewer/reviewed_at intervals. Copy beside the exact source as dataset_review.json. Empty intervals confirm nothing.",
                "intervals": []})
            inventory.append({"source": ep["relative"], "hashes": ep["files"]})
            counts["raw_records"] += len(ep["rows"])
            counts["orphan_images"] += orphan_images
            counts["event_records"] += len(events)
            next_time = ep["rows"][0]["timestamp_seconds"]
            for row in ep["rows"]:
                stamp = row["timestamp_seconds"]
                if stamp + 1e-7 < next_time:
                    continue
                next_time = stamp + stride
                sample_id = "sample-" + digest([ep["id"], row["frame"], horizon, "rgb_speed_base_action_v1"])[:24]
                targets = {h: target(ep, row, h, horizon, events, event_errors) for h in HAZARDS}
                category = "positive" if any(t["value"] == 1 for t in targets.values()) else "negative" if all(t["value"] == 0 for t in targets.values()) else "unknown"
                nearby_misses = [e for e in events if e["event_type"] in ("near_miss", "red_light_encroachment") and e["timestamp_seconds"] is not None and stamp <= e["timestamp_seconds"] <= stamp + horizon]
                probability = negative_keep if assignment["split"] == "train" and category == "negative" and not nearby_misses else 1.
                if int(digest([seed, sample_id])[:12], 16) / float(16 ** 12) >= probability:
                    counts["downsampled_training_negatives"] += 1
                    continue
                image, alignment, input_errors = image_input(root, ep, row)
                speed = row.get("ego", {}).get("speed_mps")
                if not finite(speed) or speed < 0:
                    input_errors.append("invalid_speed")
                    speed = None
                if ep["policy"] not in ("behavior_agent", "simlingo"):
                    input_errors.append("unsupported_or_synthetic_policy")
                if "synthetic" in str(ep["manifest"]).lower() or "synthetic" in str(ep["backend"]).lower():
                    input_errors.append("synthetic_episode")
                if not assignment["geometry_verified"]:
                    input_errors.append("route_geometry_unverified")
                if ep["delta"] is None or ep["delta"] <= 0:
                    input_errors.append("timing_unverified")
                if nearby_misses:
                    input_errors.append("unreviewed_near_miss_or_legacy_encroachment")
                if event_errors:
                    input_errors.extend(event_errors)
                if ep["official"] and ep["official"].get("collection_integrity") != "pass":
                    input_errors.append("official_collection_integrity_failed")
                if any(e["event_type"] in HAZARDS and e["timestamp_seconds"] is not None and e["timestamp_seconds"] <= stamp for e in events):
                    input_errors.append("at_or_after_hazard_event")
                for hazard, target_value in targets.items():
                    target_value["loss_mask"] = target_value["loss_mask"] and not input_errors
                    labels["{}:{}".format(target_value["status"], target_value["value"])] += 1
                    hazard_counts["{}:{}:{}".format(hazard, target_value["status"], target_value["value"])] += 1
                    reasons.update(target_value["reason_codes"])
                reasons.update(input_errors)
                eligible = any(t["loss_mask"] for t in targets.values())
                sample = {"schema_version": SCHEMA_VERSION, "sample_id": sample_id, "episode_id": ep["id"],
                          "frame": row["frame"], "timestamp_seconds": stamp,
                          "time_from_episode_start_seconds": stamp - ep["rows"][0]["timestamp_seconds"],
                          "features": {"rgb": image, "speed_mps": speed, "base_action": row["base_policy_action"]},
                          "feature_profile": "rgb_speed_base_action_v1", "speed_source": "carla_ground_truth",
                          "alignment_status": alignment, "targets": targets,
                          "provenance": {"source": ep["relative"], "policy": ep["policy"],
                                         "applied_action": row["safety_supervisor_action"],
                                         "supervisor_intervened": row["supervisor_intervened"]},
                          "near_miss_evidence_ids": [e["evidence_id"] for e in nearby_misses],
                          "sampling": {"category": category, "probability": probability, "weight": 1. / probability},
                          "eligibility": {"supervised": eligible, "reason_codes": sorted(set(input_errors))}, **assignment}
                write_row(samples, sample)
                counts["samples"] += 1
                counts["supervised_samples"] += int(eligible)
                counts["verified_camera_samples"] += int(alignment == "verified")
                policies[ep["policy"] or "unknown"] += 1
                strata[assignment["split"] + ":" + category] += 1
                # A bounded queue is for human work, never automatic approval.
                if category == "positive" or (counts["samples"] % 50 == 1):
                    write_row(review_stream, {"sample_id": sample_id, "episode_id": ep["id"],
                                         "episode_sha256": ep["files"]["episode.jsonl"],
                                         "anchor_frame": row["frame"], "horizon_seconds": horizon,
                                         "targets": targets, "source": ep["relative"],
                                         "reviewed": False, "label_correct": None})
            for name, expected in ep["files"].items():
                if file_hash(contained(root, ep["path"].parent / name)) != expected:
                    raise ValueError("Source changed while processing: " + ep["relative"])
    write_json(output / "splits.json", splits)
    blockers = []
    if not counts["supervised_samples"]:
        blockers.append("no_confirmed_training_eligible_samples")
    if not splits["held_out_estimate_available"]:
        blockers.append("insufficient_independent_train_validation_test_groups")
    if not counts["verified_camera_samples"]:
        blockers.append("no_verified_camera_samples")
    if not policies["simlingo"]:
        blockers.append("simlingo_coverage_missing")
    for hazard in HAZARDS:
        if not event_counts[hazard]:
            blockers.append("missing_positive_event:" + hazard)
    blockers.append("pilot_only_no_agreed_statistical_sample_size_or_complete_hazard_coverage")
    report = {"status": "pilot_not_training_ready", "counts": dict(counts), "labels": dict(labels),
              "by_policy": dict(policies), "by_split_and_category": dict(strata),
              "reason_counts": dict(reasons), "source_failures": failures, "duplicates": duplicates,
              "episodes": len(episodes), "independent_groups": len(splits["groups"]),
              "by_hazard_status_value": dict(hazard_counts), "event_callback_counts": dict(event_counts),
              "episode_outcomes": dict(episode_outcomes),
              "blockers": blockers, "sample_content_digest": file_hash(output / "samples.jsonl"),
              "image_validation": "PNG signature/dimensions/hash; full decode belongs to loader/preflight",
              "legacy_audit_policy": "preserved in source; not promoted to horizon reviews"}
    write_json(output / "quality_report.json", report)
    priorities = []
    if not counts["verified_camera_samples"]:
        priorities.append({"action": "bounded_aligned_pilot", "reason": "No verified camera inputs; use corrected recorder first"})
    if not policies["simlingo"]:
        priorities.append({"action": "bounded_frozen_simlingo_pilot", "reason": "Behavior Agent data cannot replace the central policy comparison"})
    if not splits["held_out_estimate_available"]:
        priorities.append({"action": "select_nonoverlapping_route_groups", "reason": "Do not obtain a test set by splitting frames or repeatedly running the same geometry"})
    for hazard in HAZARDS:
        if not event_counts[hazard]:
            priorities.append({"action": "assess_missing_" + hazard + "_positive", "reason": "Inspect scenario interaction and base-policy outcomes; never assign an intended event as an observed positive"})
    priorities.append({"action": "human_future_interval_review", "reason": "Review queue and hash-bound intervals must be approved before supervised loss; no amount of rerunning substitutes for review"})
    write_json(output / "collection_plan.json", {
        "status": "review_required_before_scale_up" if counts["verified_camera_samples"] else "pilot_required", "priorities": priorities,
        "constraints": {"max_routes": 3, "wall_seconds_per_route": 600, "stop_carla_after_batch": True,
                        "no_automatic_label_approval": True, "minimum_free_disk_gb": 8},
        "deferred": ["large-scale collection until pilot review", "training", "final study-size protocol"],
        "report_blockers": blockers})
    if code_provenance(Path(project)) != provenance:
        raise ValueError("Implementation changed during build; rerun to a new output directory")
    write_json(output / "dataset_manifest.json", {
        "schema_version": SCHEMA_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": ".", "source_root_binding": "Supply the original source root to consumers; paths are root-relative",
        "configuration": {"horizon_seconds": horizon, "stride_seconds": stride, "seed": seed,
                          "training_negative_keep": negative_keep, "feature_profile": "rgb_speed_base_action_v1",
                          "label_policy": "confirmed_only", "units": {"speed": "m/s", "time": "simulation seconds"}},
        "source_inventory": inventory, "source_inventory_digest": digest(inventory),
        "code": provenance, "artifacts": {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()},
        "readiness": report["status"]})
    return report
