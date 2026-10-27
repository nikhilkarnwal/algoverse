"""Conservative geometry grouping before any sample selection."""

from av_safeplan.dataset.sources import digest, finite


def bounds(episode):
    geometry = episode["geometry"]
    if not geometry or not all(isinstance(p, dict) and finite(p.get("x")) and finite(p.get("y")) for p in geometry):
        return None
    return (min(p["x"] for p in geometry), min(p["y"] for p in geometry),
            max(p["x"] for p in geometry), max(p["y"] for p in geometry))


def assign(episodes, seed, previous=None):
    parents = list(range(len(episodes)))
    boxes = [bounds(e) for e in episodes]
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, a in enumerate(episodes):
        for j in range(i):
            b = episodes[j]
            same_map = not a["map"] or not b["map"] or a["map"] == b["map"]
            if not same_map:
                continue
            # Missing full route geometry is merged conservatively, never split
            # using partial driven paths or scenario names.
            x, y = boxes[i], boxes[j]
            overlap = x is None or y is None or not (x[2] + 30 < y[0] or y[2] + 30 < x[0] or x[3] + 30 < y[1] or y[3] + 30 < x[1])
            if overlap:
                parents[root(i)] = root(j)
    groups = {}
    for i, ep in enumerate(episodes):
        groups.setdefault(root(i), []).append(ep)
    result, group_records = {}, []
    for members in groups.values():
        signatures = sorted({digest([e["map"], e["geometry"]]) for e in members})
        group_id = "group-" + digest(signatures)[:20]
        number = int(digest([seed, group_id])[:12], 16) / float(16 ** 12)
        split = "train" if number < .70 else "validation" if number < .85 else "test"
        if len(groups) < 3:
            split = "pilot"
        for e in members:
            result[e["id"]] = {"group_id": group_id, "split": split,
                                "geometry_verified": bounds(e) is not None and bool(e["map"])}
        group_records.append({"group_id": group_id, "split": split, "episodes": sorted(e["id"] for e in members)})
    if previous:
        for episode_id, assignment in previous["assignments"].items():
            if episode_id in result and result[episode_id] != assignment:
                raise ValueError("Existing split would change; create a new dataset/split version explicitly")
    return {"seed": seed, "ratios": [.70, .15, .15], "assignments": result,
            "groups": sorted(group_records, key=lambda g: g["group_id"]),
            "grouping": "30m-expanded full-route bounding-box connected components; unknown geometry conservatively merged within map",
            "held_out_estimate_available": len(groups) >= 3 and {x["split"] for x in result.values()} >= {"train", "validation", "test"}}
