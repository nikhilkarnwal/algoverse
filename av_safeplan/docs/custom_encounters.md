# Custom training encounters (not official benchmark scenarios)

## Lead-braking pilot revision (October 31)

After the first moderate case failed to close its braking gap, the lead controller
now targets min(configured speed, max(0, ego speed minus 0.6 m/s)), with bounded
throttle/brake. The actual braking trigger additionally requires same-lane,
aligned following, ego speed >=1 m/s, lead speed >=0.5 m/s, and a positive bumper
gap between 2 m and the configured threshold. Gap/speeds are logged every 0.5 s.
Exhausted encounter envelopes and timeouts request clean route termination with
censored encounter evidence rather than throwing a runtime exception. They do
not constitute successful hazard validation. Ego controls remain unchanged.

`purpose: single_encounter_pilot` explicitly permits one encounter; normal
catalogs still require 3–5. One moderate pilot was authorized with a 600-second
post-initialization cap; it does not authorize running the remaining cases.
Live results are pending in `lead-pilot-20261031-v1`; older implementation-only
notes below describe the original delivery, not the latest run status.

Implementation only: no CARLA run, deployment, collection, or model training has
been launched. Live validation and a separately approved bounded run plan remain
required. Do not interpret Python syntax checks as driving validation.

## Six configurations

| Case | Parameters |
| --- | --- |
| lead_brake_moderate | Lead target speed 6 m/s, braking at bumper gap <=20 m, brake 0.45 |
| lead_brake_hard | Lead target speed 6 m/s, braking at bumper gap <=12 m, brake 1.0 |
| pedestrian_early | Crossing speed 1.3 m/s, trigger distance 25 m |
| pedestrian_late | Crossing speed 2.5 m/s, trigger distance 14 m |
| obstacle_wide | Stationary vehicle obstacle, target passing space 3.5 m |
| obstacle_tight | Stationary vehicle obstacle, target passing space 2.7 m |

Brake values are normalized CARLA commands, not guaranteed decelerations. Actual
braking and clearance require live inspection. Crossing timing does not imply a
collision. Static obstacles currently use a parked Lincoln vehicle; they are not
cone/pedestrian or generic-object collision evidence.

Each route has three encounters at 45, 155 and 265 m by default. Three to five
are configurable. Actors are placed ahead during initialization, before driving;
only one encounter is active at a time. Activation begins within 35 m after at
least three seconds of simulation stabilization. Actors remain visible: no hiding,
teleporting into the ego, or control override. Each encounter must be passed by
12 m before advancing. A lead actor leaving its 40 m envelope or a 60-s simulated
encounter timeout ends the run as incomplete, rather than falsely clearing it.

The route collision criterion terminates the episode on the first detected ego
collision, including contacts outside the active encounter. Remaining hazards
are not attempted automatically. A fresh world/episode and separately approved
run are required to collect later encounters after a collision. Keep a wall-clock
watchdog around every live run (the existing collection watchdog can be reused).

## Placement requirements

The initial implementation deliberately requires a flat straight, junction-free
corridor on one road/section/lane. It samples that corridor every 2 m and rejects
invalid geometry. The ego must initialize within 8 m of the trigger anchor.
Pedestrians require sidewalks at both crossing endpoints (the initial version
does not cross additional lanes). Obstacles require a continuous same-direction
left passing lane and enough actual bounding-box clearance for the ego plus
0.5 m. Actor overlap/spawn failures are fatal; custom loader errors must not be
silently skipped. Actual sidewalk accessibility, background-traffic interactions,
actor motion, and camera visibility still need live review.

All six configurations at a location share a single training group; repeated
encounters are correlated, not independent locations. Reserve and audit training
coordinates against all held-out geometry before preparing live runs. Do not
select locations using held-out outcomes. The generator marks geometry and split
audit pending; it does not invent a valid map anchor or certify independence.

## Preparation (offline only)

`scripts/prepare_custom_encounters.py` takes an explicitly selected anchor:
`--town`, `--x`, `--y`, `--z`, `--yaw`, `--training-location-id`, and a new
`--output-dir`. It writes six individual route XML files, a catalog snapshot,
hashes, and a train-only manifest. It does not contact CARLA. A seed is recorded;
the run stack must use that same seed. Anchor selection is intentionally left for
the approved live-preflight plan, not copied from validation routes.

After approval, the existing SimLingo evaluator accepts `--custom-catalog PATH`
alongside `--routes ONE_CASE.xml --output-dir NEW_RUN`. This opts into
`custom_leaderboard_entry.py`, which registers the ScenarioRunner class in the
evaluator process and enables collision termination. No upstream checkout is
edited. Without that flag, the official path is unchanged. One recorded attempt
per fresh evaluator process is required; repetitions and recording-disabled
custom runs are refused. Start/stop CARLA and finalization remain the existing
EC2 wrapper's responsibility; do not bypass its cleanup or time limits.

## Evidence and eligibility

Existing SimLingo image/telemetry and official route results remain available.
Additional `custom_encounters/*.jsonl` logs contain case, encounter ID, actor ID,
simulation frame/time, parameters, activation/trigger/clear/timeout and
not-completed states. Use these timestamps to associate telemetry with encounters;
do not equate a `cleared` record with a reviewed negative label. Collision counts
must come from recorded sensor evidence, never scenario names or difficulty.

Reviews are deferred and loss masks false. Existing candidate-label finalization
still requires a separate invocation; this feature does not admit any sample to
training. Exclude post-contact windows and censor unobserved horizons. Keep safe
outcomes, timeouts, skipped encounters, and any setup failures in the collection
inventory. Future reporting must separate callbacks, overlapping windows,
encounter clusters, and independent locations.

## Next approved-run proposal

1. Reserve a training-only compatible corridor; verify held-out separation.
2. Prepare the six XML files and freeze their manifest/configuration hashes.
3. Conduct a bounded geometry/actor-placement preflight and inspect clearance.
4. Run one short pilot per family with frozen SimLingo and first-collision stop.
5. Verify evidence alignment, intended triggers and cleanup before scaling.

No automatic retries or outcome-driven tuning against validation/test routes.
