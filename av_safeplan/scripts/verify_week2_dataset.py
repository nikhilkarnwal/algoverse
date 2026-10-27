#!/usr/bin/env python3
"""Read-only integrity audit of a real dataset build; no simulator or training."""

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from av_safeplan.dataset.sources import contained, file_hash, read_json, read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--decode-images", action="store_true", help="Also decode PNGs with existing Pillow; never installs it")
    parser.add_argument("--compare", type=Path, help="Compare another build's deterministic samples and splits")
    parser.add_argument("--output", type=Path, help="New external report path; not inside the immutable dataset")
    args = parser.parse_args()
    source, dataset = args.source_root.resolve(), args.dataset.resolve()
    failures, checked_images, checked_samples = [], set(), set()
    manifest = read_json(dataset / "dataset_manifest.json")
    for name, expected in manifest["artifacts"].items():
        path = contained(dataset, dataset / name)
        if not path.is_file() or file_hash(path) != expected:
            failures.append("artifact_hash:" + name)
    episodes = {ep["episode_id"]: ep for ep in read_rows(dataset / "episodes.jsonl")}
    raw = {}
    for episode_id, episode in episodes.items():
        path = contained(source, source / episode["source"])
        for name, expected in episode["source_hashes"].items():
            item = contained(source, path.parent / name)
            if not item.is_file() or file_hash(item) != expected:
                failures.append("source_hash:" + str(item.relative_to(source)))
        raw[episode_id] = {row["frame"]: row for row in read_rows(path)}
    evidence = {e["evidence_id"]: e for e in read_rows(dataset / "evidence.jsonl")}
    splits = read_json(dataset / "splits.json")
    groups = {}
    for assignment in splits["assignments"].values():
        groups.setdefault(assignment["group_id"], set()).add(assignment["split"])
    if any(len(x) != 1 for x in groups.values()):
        failures.append("group_leakage")
    for sample in read_rows(dataset / "samples.jsonl"):
        sid = sample["sample_id"]
        if sid in checked_samples:
            failures.append("duplicate_sample:" + sid)
        checked_samples.add(sid)
        row = raw[sample["episode_id"]][sample["frame"]]
        if set(sample["features"]) != {"rgb", "speed_mps", "base_action"}:
            failures.append("feature_whitelist:" + sid)
        if sample["features"]["base_action"] != row["base_policy_action"]:
            failures.append("action_alignment:" + sid)
        if sample["timestamp_seconds"] != row["timestamp_seconds"]:
            failures.append("timestamp_alignment:" + sid)
        for key in ("group_id", "split"):
            if sample[key] != splits["assignments"][sample["episode_id"]][key]:
                failures.append("split_assignment:" + sid)
        for hazard, target in sample["targets"].items():
            start = sample["timestamp_seconds"]
            end = start + target["horizon_seconds"]
            if target["value"] == 0 and target["coverage_end_seconds"] + 1e-7 < end:
                failures.append("censored_negative:" + sid)
            if target["value"] == 1:
                hits = [evidence[eid] for eid in target["evidence_ids"]]
                if not hits or not any(e["event_type"] == hazard and start < e["timestamp_seconds"] <= end + 1e-7 for e in hits):
                    failures.append("positive_outside_horizon:" + sid)
            if target["loss_mask"] and (target["status"] != "confirmed" or sample["alignment_status"] != "verified" or not target["review_ids"]):
                failures.append("unverified_loss_mask:" + sid)
        image = sample["features"]["rgb"]
        if image and image["path"] not in checked_images:
            checked_images.add(image["path"])
            path = contained(source, source / image["path"])
            if file_hash(path) != image["sha256"]:
                failures.append("image_hash:" + image["path"])
            if args.decode_images:
                from PIL import Image
                try:
                    with Image.open(path) as frame:
                        frame.load()
                        if frame.size != (image["width"], image["height"]):
                            failures.append("image_size:" + image["path"])
                except (OSError, ValueError):
                    failures.append("image_decode:" + image["path"])
    if args.compare:
        for name in ("samples.jsonl", "splits.json", "evidence.jsonl"):
            if file_hash(dataset / name) != file_hash(args.compare / name):
                failures.append("nonreproducible:" + name)
    result = {"integrity_status": "fail" if failures else "pass", "samples_checked": len(checked_samples),
                      "images_checked": len(checked_images), "full_image_decode": args.decode_images,
                      "failures": failures, "semantic_label_review": "not performed; human review remains required"}
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        report = args.output.resolve()
        if report == dataset or dataset in report.parents:
            parser.error("verification report must be outside the immutable dataset")
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x") as stream:
            stream.write(payload)
    print(payload)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
