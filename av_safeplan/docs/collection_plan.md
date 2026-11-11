# Broad-collision collection and evaluation plan

Status: broader scope approved; scenario implementation and collection runs remain
planned and require approval of the execution plan. No new runs are authorized by
this document. This supersedes the junction-only plan as the complete coverage plan;
the eight-episode junction pilot remains a red-light sub-batch only.

**Source constraint:** use existing ScenarioRunner behavior implementations and
official configurations, not custom-designed encounter logic. The installed-source
[scenario shortlist](scenario_runner_shortlist.md) includes the seven additionally
requested scenarios and distinguishes Town12 entries from standalone examples in
other towns. The previous custom signalized wrapper is not the default for new
upstream-only collection; historical data is preserved. Execution configuration
changes and live compatibility validation remain pending.

## Task boundary

Keep two binary future-horizon targets: any collision and red-light violation.
Collision includes vehicles, pedestrians, and static objects. Do not add three
model output heads merely to track coverage. Collision category is label/evaluation
metadata, never a privileged inference feature. Preserve original actor type,
event frame, impulse and review evidence. Multiple collision categories can occur
in one horizon; retain all categories rather than forcing a single class.

The current sensor accepts all reported collisions, but the curated pilot has
only two vehicle collision events (firetruck and police car). It does not establish
pedestrian or static-object coverage. Category normalization, per-category reporting,
new scenario adapters and coverage gates are planned, not already implemented.

## Required scenario matrix

| Category | Conflict families | Matched safe encounters | Review evidence |
|---|---|---|---|
| Vehicle | Lead braking, cross traffic; later cut-in if reliable | Safe following/braking and yielding | Contact actor/type, onset, collision sensor and official criteria |
| Pedestrian | Visible crossing, then occluded emergence | Ego yields or pedestrian clears safely | Confirm pedestrian identity, actual contact or full safe horizon, visibility and timing |
| Static object | Barrier or obstacle blocking an otherwise drivable lane | Safe stop or pass with clearance | Object identity/collision geometry, contact onset, route/lane context |
| Red-light violation | Existing signalized approach and transition conditions | Stop before the controlling stop line; compliant crossing | Ego-lane light/arrow, stop line and synchronized signal/crossing time |

A parked vehicle remains vehicle-category, not static-object category merely because
it is stationary. Define bicycle/rider treatment and ambiguous object mappings before
collection; retain unknown/mixed cases explicitly, never silently discard them.
Do not invent an impulse/severity threshold or use near-miss flags as collision labels.
Unexpected road/curb contacts need explicit adjudication, not an automatic safe label.

## Staged execution proposal

1. Resolve the existing near-miss veto on independently confirmed collision targets
   through an explicit dataset-policy review. Do not approve a near miss to bypass it.
2. Add versioned collision-category metadata/reporting, scenario encounter categories
   for negatives, and coverage gates. Negatives are tagged by encounter context, not
   by an absent collision actor. Keep raw data and previous dataset versions unchanged.
3. Inspect installed upstream pedestrian and obstacle scenarios for compatibility,
   actor placement and termination behavior. Validate one representative setup per
   category before scaling. Signalized-junction selection alone does not supply these.
4. Choose spatially separate route groups for each category; reserve held-out locations
   before outcomes. Keep both policies, reruns, weather and timing variants of each
   location in one split. Resolve actual road connectivity and review visibility.
   The current offline junction proposals are provisional and not yet assigned splits.
5. Run separately approved, bounded sub-batches with unchanged Behavior Agent and
   frozen SimLingo: vehicle coverage, pedestrian coverage, static-object coverage, and
   red-light coverage. The earlier two-junction × two-timing × two-policy batch is
   eight episodes for red-light coverage, not the entire broader experiment.
6. Review positive events and complete negative horizons for every category; rebuild,
   audit masks/geometry and inspect coverage before requesting another batch.

Use the existing installed stack; do not schedule the expanded campaign until exact
scenario configurations, episode counts and wall-clock caps are presented and approved.
Begin each new family with a small diagnostic run; stop for skipped scenarios, missing
actors, sensor mismatch or resource errors. Stop CARLA after batches. EC2 shutdown is
a separate user choice. No silent extension of the previous 90-minute junction budget.

Outcomes are not guaranteed. If a frozen policy avoids all conflicts, record the lack
of positives and propose another bounded configuration. Forced-control collisions are
detector diagnostics only; segregate them from natural frozen-policy risk data. Never
change the policy and label the result as frozen-policy behavior.

## Evaluation and readiness gates

- Publish overall collision results AND vehicle/pedestrian/static-object breakdowns,
  separately by base policy. Report red-light results separately.
- Count distinct events, episodes and physical locations as well as sampled windows.
  Fifteen overlapping windows before one impact are not fifteen independent crashes.
- Require reviewed positive events and safe encounters for each claimed category in
  train, validation and held-out evaluation. Missing cells are unavailable, not zero
  risk or perfect performance. Agree sample-size targets before large collection.
- Evaluate recall/missed hazards, precision/false alarms, discrimination and calibration
  with per-category support counts; do not claim a stable metric without sufficient
  independent support. Select thresholds on validation only and report held-out results
  without tuning on them. Report uncertainty at route/episode level, not as if windows
  were independent.
- Keep static-object or pedestrian performance claims pending until corresponding
  recorded and reviewed evidence exists. A good overall score dominated by vehicle
  samples is not evidence of broad collision safety.

## Current reviewed pilot

`week2-reviewed-v1`: 626 samples, 17 confirmed targets from three human approvals.
Two negative target losses are enabled. Fifteen confirmed collision-positive targets
remain excluded by the unreviewed-near-miss rule. No pedestrian/static-object collision
positives, red-light positives or held-out test group are established. The later route-2
crossing remains unverified because the controlling signal is outside the image view.
