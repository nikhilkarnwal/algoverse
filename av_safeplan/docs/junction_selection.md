# Outcome-blind junction selection

`scripts/report_junction_candidates.py` is a CPU-only pre-screen, not a simulator
launcher or final declaration of junction independence. It reads official
signalized left/right-turn scenario triggers and the complete recorded route
geometry of an existing dataset. It never reads driving outcomes to rank sites.

```bash
python scripts/report_junction_candidates.py \
  --routes /home/ubuntu/av-safeplan-runtime/external/leaderboard/data/routes_devtest.xml \
  --routes /home/ubuntu/av-safeplan-runtime/external/leaderboard/data/routes_training.xml \
  --routes /home/ubuntu/av-safeplan-runtime/external/leaderboard/data/routes_validation.xml \
  --dataset /home/ubuntu/av-safeplan-runtime/outputs/datasets/week2-reviewed-v1 \
  --source-root /home/ubuntu/av-safeplan-runtime/outputs/trajectories \
  --output /home/ubuntu/av-safeplan-runtime/outputs/upstream/junction-candidates-v1
```

Choose a new output directory on reruns; existing reports are not overwritten.
No additional dependencies, simulator, training or GPU activity are required.

## Screening semantics

- Each trigger gets a proposed 200m-radius square route-containment envelope.
  This is conservative planning geometry, not a traced executable route.
- The separation predicate matches the current splitter: a greater-than-30m gap
  on at least one coordinate axis. It is not 30m inflation of both boxes.
- Overlapping candidate envelopes are grouped transitively. A group touching any
  existing route box is excluded. One candidate per remaining group can be proposed.
- Selection uses stable candidate-ID order, never score or violation outcomes.
- IDs incorporate source XML hashes, source route/scenario identity and trigger
  coordinates. Preserve the report if upstream XML changes.
- Existing manifest hashes must match the dataset inventory. Missing route/map
  geometry fails closed rather than claiming independence.

## First scan

The installed Town12 route files yielded 244 scenario entries and nine eligible
conservative clusters. These are not 244 distinct physical junctions.

| Intended use | Candidate | Trigger x,y (metres) | Scenario |
|---|---|---|---|
| Proposed test | junction-candidate-07a8e0a92a95d76c | 2661.2, 4212.2 | Left turn |
| Proposed development | junction-candidate-2b352344a8ac2221 | 1751.8, 5756.7 | Left turn |

Both happen to be left turns; layout diversity is not yet established. The
coordinates describe upstream scenario triggers, not junction centers.

## Required next gate

A separately approved bounded CARLA map inspection must trace the short road
routes and confirm they stay inside the proposed envelopes, resolve physical
junction IDs and ego-lane controlling lights/stop lines, and check visibility.
Recompute overlap using all actual route geometry. A route leaving its envelope
is rejected and requires a new report. Do not silently move or shrink it to pass.

The proposed test assignment is not applied by this report. The current dataset
splitter uses deterministic hashing and does not implement a manual reservation.
Add an explicit, reviewed reservation contract before collection; preserve existing
assignments and keep all policies, timing variants and reruns at a location together.
The final held-out assignment must be frozen before outcomes are observed.

The first report is `/home/ubuntu/av-safeplan-runtime/outputs/upstream/junction-candidates-v1/`.
It includes full JSON provenance/conflict details and a concise Markdown summary.
