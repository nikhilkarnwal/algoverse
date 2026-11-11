"""Collision coverage metadata; never inference features or label approval."""

from collections import Counter

VERSION = "collision-category-v1"
CATEGORIES = ("vehicle", "pedestrian", "static_object", "unknown")
BICYCLES = {"vehicle.bh.crossbike", "vehicle.diamondback.century", "vehicle.gazelle.omafiets"}


def classify(actor_type):
    actor_type = actor_type if isinstance(actor_type, str) else ""
    if actor_type.startswith("walker.pedestrian."):
        category, subtype = "pedestrian", "pedestrian"
    elif actor_type.startswith("vehicle."):
        category, subtype = "vehicle", "bicycle" if actor_type in BICYCLES else "other_vehicle"
    elif actor_type.startswith("static.prop."):
        category, subtype = "static_object", "prop"
    else:
        category, subtype = "unknown", "unmapped"
    return {"category": category, "subtype": subtype, "mapping_version": VERSION,
            "classification_source": "recorded_actor_type", "classification_reviewed": False}


def collision_metadata(target, evidence):
    hits = sorted((evidence[eid] for eid in target["evidence_ids"]),
                  key=lambda e: (e["timestamp_seconds"], e["evidence_id"]))
    categories = sorted({e["collision_classification"]["category"] for e in hits})
    return {"mapping_version": VERSION, "future_event_categories": categories,
            "mixed": len(categories) > 1,
            "first_event_category": hits[0]["collision_classification"]["category"] if hits else None,
            "category_evidence_ids": {c: [e["evidence_id"] for e in hits if e["collision_classification"]["category"] == c]
                                      for c in categories},
            "encounter_categories": ["unknown"],
            "encounter_status": "not_annotated_no_inference_from_absent_collision"}


class Coverage:
    """Counts callbacks and actor contacts explicitly, not independent crashes."""

    def __init__(self):
        self.cells = {}
        for category in CATEGORIES:
            for policy in ("behavior_agent", "simlingo"):
                for split in ("train", "validation", "test", "pilot"):
                    self.cell(category, policy, split)

    def cell(self, category, policy, split):
        key = (category, policy or "unknown", split)
        return self.cells.setdefault(key, {"counts": Counter(), "episodes": set(), "groups": set(),
                                           "actor_contacts": set(), "subtypes": Counter(), "exclusions": Counter()})

    def episode(self, ep, assignment, events):
        for event in events:
            if event["event_type"] != "collision":
                continue
            classification = event["collision_classification"]
            cell = self.cell(classification["category"], ep["policy"], assignment["split"])
            cell["counts"]["collision_callbacks"] += 1
            cell["subtypes"][classification["subtype"]] += 1
            cell["episodes"].add(ep["id"])
            cell["groups"].add(assignment["group_id"])
            actor = event["details"].get("other_actor_id")
            if actor is None:
                cell["counts"]["callbacks_missing_actor_id"] += 1
            else:
                cell["actor_contacts"].add((ep["id"], actor))

    def sample(self, sample):
        target = sample["targets"]["collision"]
        metadata = sample["collision_metadata"]
        categories = metadata["future_event_categories"] if target["value"] == 1 else metadata["encounter_categories"]
        for category in categories:
            cell = self.cell(category, sample["provenance"]["policy"], sample["split"])
            value = target["value"]
            cell["counts"]["positive_windows" if value == 1 else "negative_windows" if value == 0 else "unknown_windows"] += 1
            # Combined-target approval applies to the FIRST onset only. Do not
            # claim a later different category's onset was also reviewed.
            scoped = value == 0 or category == metadata["first_event_category"]
            if scoped and target["status"] == "confirmed":
                cell["counts"]["confirmed_first_onset_windows" if value == 1 else "confirmed_negative_windows"] += 1
            if scoped and target["loss_mask"]:
                cell["counts"]["eligible_positive_windows" if value == 1 else "eligible_negative_windows"] += 1
            cell["exclusions"].update(sample["eligibility"]["reason_codes"])

    def report(self):
        rows = []
        keys = ("collision_callbacks", "callbacks_missing_actor_id", "positive_windows", "negative_windows", "unknown_windows",
                "confirmed_first_onset_windows", "confirmed_negative_windows", "eligible_positive_windows", "eligible_negative_windows")
        for (category, policy, split), cell in sorted(self.cells.items()):
            counts = {key: cell["counts"][key] for key in keys}
            rows.append({"category": category, "policy": policy, "split": split, **counts,
                         "episodes_with_collisions": len(cell["episodes"]), "groups_with_collisions": len(cell["groups"]),
                         "unique_episode_actor_contacts": len(cell["actor_contacts"]),
                         "callback_subtypes": dict(cell["subtypes"]), "exclusion_reasons": dict(cell["exclusions"]),
                         "coverage_status": "present" if counts["positive_windows"] or counts["negative_windows"] else "missing"})
        return {"mapping_version": VERSION, "cells": rows,
                "limitations": ["Actor classification is automatic, not human-approved",
                    "Bicycles are retained as vehicle/bicycle, never pedestrian; report subtype separately",
                    "Callback and unique episode/actor counts are not independent crash counts",
                    "Geometric groups are not verified physical junction counts",
                    "Negative encounter categories remain unknown until explicit scenario evidence is recorded",
                    "Confirmed first-onset windows do not approve other categories later in the horizon",
                    "Mixed-category windows appear in multiple cells; cells are not additive",
                    "Coverage is not a performance or training-readiness claim"]}
