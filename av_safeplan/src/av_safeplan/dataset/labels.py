"""Future-window targets with explicit review, censoring and interventions."""

from av_safeplan.dataset.sources import digest

HAZARDS = ("collision", "red_light_violation")


def extract_evidence(episode):
    frames = {r["frame"]: r["timestamp_seconds"] for r in episode["rows"]}
    evidence, seen, errors = [], set(), []
    for row in episode["rows"]:
        for event in row["events"]:
            if not isinstance(event, dict):
                errors.append("malformed_event")
                continue
            identity = digest([episode["id"], event])
            if identity in seen:
                continue
            seen.add(identity)
            frame = event.get("frame")
            stamp = frames.get(frame)
            if stamp is None:
                errors.append("unmapped_event_frame")
            evidence.append({"evidence_id": identity, "episode_id": episode["id"],
                             "event_type": event.get("event_type"), "frame": frame,
                             "timestamp_seconds": stamp, "emitted_frame": row["frame"],
                             "details": event.get("details", {}), "source_sha256": episode["files"]["episode.jsonl"]})
    return evidence, sorted(set(errors))


def reviewed(episode, hazard, value, first, last):
    matches = []
    for review in episode["review"].get("intervals", []):
        if (review.get("hazard") == hazard and review.get("value") == value
                and review.get("reviewed") is True and review.get("label_correct") is True
                and review.get("start_frame", float("inf")) <= first
                and review.get("end_frame", -1) >= last
                and review.get("reviewer") and review.get("reviewed_at")):
            matches.append(digest(review))
    return matches


def rejected(episode, hazard, value, first, last):
    return any(r.get("hazard") == hazard and r.get("value") == value
               and r.get("reviewed") is True and r.get("label_correct") is False
               and r["start_frame"] <= last and r["end_frame"] >= first
               for r in episode["review"].get("intervals", []))


def target(episode, row, hazard, horizon, evidence, event_errors):
    start = row["timestamp_seconds"]
    end = start + horizon
    rows = episode["rows"]
    coverage_end = rows[-1]["timestamp_seconds"]
    hits = sorted([e for e in evidence if e["event_type"] == hazard
                   and e["timestamp_seconds"] is not None and start < e["timestamp_seconds"] <= end + 1e-7],
                  key=lambda e: (e["timestamp_seconds"], e["evidence_id"]))
    result = {"value": None, "status": "unknown", "loss_mask": False,
              "horizon_seconds": horizon, "coverage_end_seconds": coverage_end,
              "evidence_ids": [e["evidence_id"] for e in hits], "review_ids": [], "reason_codes": []}
    stop = min((e["timestamp_seconds"] for e in hits), default=end)
    relevant = [r for r in rows if start <= r["timestamp_seconds"] < stop + 1e-7]
    # The action at the event frame cannot cause an already-observed event.
    if any((r["supervisor_intervened"] or r["base_policy_action"] != r["safety_supervisor_action"])
           and r["timestamp_seconds"] < stop - 1e-7 for r in relevant):
        result["reason_codes"].append("intervened_rollout")
        return result
    if hits:
        result.update(value=1, status="candidate")
        # Bind review and intervention coverage to the same first occurrence;
        # a later reviewed event cannot approve an earlier unreviewed onset.
        first = hits[0]
        result["review_ids"] = reviewed(episode, hazard, 1, first["frame"], first["frame"])
        reject = rejected(episode, hazard, 1, first["frame"], first["frame"])
    else:
        if coverage_end + 1e-7 < end:
            result["reason_codes"].append("right_censored")
        if any(a < end and b > start for a, b in episode["gaps"]):
            result["reason_codes"].append("coverage_gap")
        if event_errors:
            result["reason_codes"].extend(event_errors)
        if not episode["manifest"].get("detectors", {}).get(hazard):
            result["reason_codes"].append("detector_coverage_unverified")
        if result["reason_codes"]:
            return result
        result.update(value=0, status="candidate")
        last = next((r["frame"] for r in rows if r["timestamp_seconds"] + 1e-7 >= end), rows[-1]["frame"])
        result["review_ids"] = reviewed(episode, hazard, 0, row["frame"], last)
        reject = rejected(episode, hazard, 0, row["frame"], last)
    if reject:
        result.update(value=None, status="rejected")
        result["reason_codes"].append("review_rejected_or_conflicting")
    elif result["review_ids"]:
        result.update(status="confirmed", loss_mask=True)
    else:
        result["reason_codes"].append("requires_scoped_human_review")
    return result
