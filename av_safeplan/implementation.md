# Implementation Plan

## Week 1 — Environment, Policy Interfaces, Scenarios, and Labels

- Pin the CARLA version and dependency stack required for the selected SimLingo checkpoint; verify Behavior Agent in the same environment where feasible.
- Bring up Town12 in synchronous mode with a fixed simulation step and deterministic seed handling.
  - Implementation includes stable route IDs, explicit spawn/destination replay, CARLA and Traffic Manager seeding, per-run manifests, and a trajectory replay comparator.
  - Completion gate: run the same Town12 route twice in the target Colab runtime and confirm drift remains within the configured replay tolerances.
- Implement a common base-policy interface: observation → steering, throttle, and brake.
  - Implemented as a backend-neutral observation and validated control-command contract.
- Integrate Behavior Agent and validate reproducible closed-loop routes.
  - Behavior Agent now runs through the common policy interface and deterministic replay manifests/comparison.
- Integrate the frozen SimLingo driving policy behind the same policy/control interface.
  - A lazy adapter wraps the official frozen Leaderboard agent and a launcher runs the pinned upstream evaluator.
  - Baseline closed-loop evidence: `simlingo-route2-20261024T062511Z/simulation_results.json`
    completed Town12 route 2 with 100% completion, score 96.926889, no collision,
    red-light, or stop-sign violations, and two minimum-speed penalties.
  - The working evaluator wrapper now binds the already-loaded agent to the
    common policy interface and records shared episodes, pass-through decisions,
    candidate safety events, existing front-camera PNG frames, and MP4 video.
    Validated by `week2-simlingo-20261027T011413Z`: 100% route completion,
    score 100, no official infractions, 346 aligned records/images and 346 fully
    decoded MP4 frames at 20 fps. `recording_integrity.json` verifies unchanged
    pass-through actions and camera/world timing; it does not approve labels.
- Build a shared logger for:
  - Ego state
  - Nearby actors
  - Traffic lights
  - Route state
  - Base-policy action
  - Safety-supervisor action
  - Collision and red-light events
  - Seed, route, policy, and scenario parameters
  - Implemented as per-tick `episode.jsonl` telemetry plus run-level `manifest.json` outcomes.
- Implement collision and red-light event-label logic.
  - Implemented collision-sensor, red-light encroachment/violation, and near-miss labels.
- Manually audit positive, negative, and near-miss episodes.
  - Audit-queue generation is implemented; human review remains a required completion gate.
- Build controlled scenario families without adding more hazard categories.
  - The first custom YAML matrix remains available for diagnostics, but the
    October 22 review found that process completion was not sufficient evidence:
    cross-traffic produced a real collision, lead-brake produced a safe stop, and
    both red-light runs missed the intended signal interaction.
  - The reduced evidence path is therefore migrating to ScenarioRunner v0.9.15
    and public Leaderboard 2.0 Town12 route definitions. `config/upstream_scenarios.yaml`
    pins the sources and maps the Week 1 families to upstream scenarios/criteria.
  - `scripts/setup_upstream_scenarios_ec2.sh` fetches source and route XML only;
    it does not download a large sensor dataset. `scripts/prepare_week1_upstream_routes_ec2.sh`
    extracts one deterministic Town12 route per required family and crops it to
    a bounded window around the selected scenario trigger.
  - `scripts/scenario_runner_behavior_agent.py` keeps the existing BasePolicy,
    safety supervisor, episode logger, event labels, and RGB frame output while
    ScenarioRunner owns actor placement, route execution, and official criteria.
  - A scenario now needs an explicit `validation.status: pass` field in its
    manifest before `check_week1_completion.py` will count it as passed.

### Collision Scenario Families

- Lead-vehicle sudden braking
- Cross-traffic or intersection conflict
- Cut-in or lane intrusion, where supported
- Optional occluded or late-emerging actor conflicts, if reliable

### Red-Light Scenario Families

- Straight approach to an existing red signal
- Green/yellow-to-red transition during approach
- Different approach speeds and distances
- Lead-vehicle and no-lead-vehicle conditions
- Intersection-geometry variations

### Week 1 Checkpoint

Both policy adapters should run through the common interface, Town12 scenarios should be replayable, and collision/red-light labels should pass manual audit.

The EC2 completion workflow begins with
`scripts/run_week1_behavior_validation_ec2.sh`. Its replay evidence remains
valid, but its original custom scenario results are diagnostic evidence only.
The official-scenario migration is run with
`scripts/run_week1_upstream_behavior_ec2.sh`; it writes ScenarioRunner criteria
separately from AV SafePlan telemetry/images so that the authoritative simulator
result and our labels can be audited together. `week1_status.json` remains
`pending` until official scenario criteria, human label audit, and the frozen
SimLingo closed-loop result pass.

The refreshed EC2 checkpoint links the successful SimLingo baseline and marks
that gate passed. Positive and negative audit approvals each count one; genuine
near-miss approval remains zero. The shared SimLingo recording path is now
live-validated by the completed Week 2 pilot and its recording integrity report.

If SimLingo is not stable enough for large runs, use Behavior Agent for pipeline debugging while SimLingo integration continues in parallel. Keep the central scientific comparison unchanged.

## Week 2 — Training-Data Preparation

- [x] Step 1: define the versioned [dataset specification](docs/dataset_spec.md)
  against current telemetry: inference inputs, base-policy actions, future
  collision/red-light targets, provenance, audit scope, truncated-future masks,
  and route/scenario-group splits. Defaults are versioned pilot settings, not a
  final research protocol.
- [x] Step 2: implement the CPU-only converter in `src/av_safeplan/dataset/` and
  `scripts/build_week2_dataset.py`; process one episode at a time, preserve raw
  sources and hashes, reject invalid controls/timestamps and mask incomplete futures.
- [x] Step 3: generate event-ahead candidate windows at a configurable stride,
  with train-only negative downsampling, probabilities and review templates.
- [x] Step 4: implement conservative geometry-connected grouping and deterministic
  assignments; preserve reruns/policies in one group and reject changed frozen splits.
- [x] Step 5: produce quality/collection reports and a read-only artifact auditor.
  Real-data image decoding and repeat-build sample/split comparisons passed.
- [x] Step 6: execute a bounded three-route Behavior Agent pilot plus one seeded
  cross-traffic rerun, correcting sensor frame recording, cleanup-time metadata,
  and applied seed provenance. All four routes completed with collection integrity
  passing; collision outcomes are retained as evidence, not mistaken for collector bugs.
  A frozen-SimLingo cross-traffic pilot also completed with score 100 and verified
  shared logs, controls, camera alignment, and complete video.
- [ ] Review future-horizon target intervals with source-hash-bound human approval.
- [ ] Establish adequate independent train/validation/test coverage, including
  both hazard positives and adequate policy coverage, before training-readiness sign-off.

Run instructions: [Week 2 runbook](docs/week2_runbook.md). The final five-episode
curated pilot (`outputs/datasets/week2-curated-v1`) contains 626 samples from
2,492 frames: 539 Behavior Agent and 87 SimLingo samples. All 626 sampled camera
joins and full image decodes passed, and a separate rebuild reproduced samples,
splits, and evidence exactly. Thirty windows precede two recorded collision
events; zero targets are yet human-approved for loss. There are three geometry
groups but no test split, and no red-light-positive event. The pilot is explicitly
not training-ready. No model training is part of Week 2.

Week 1 carry-over remains open: genuine near-miss review. Completed shared
SimLingo recording validation is now supported by the Week 2 run above. The older
`simlingo-route2-20261024T072202Z` timeout remains diagnostic evidence only; its
partial outputs are not included in the curated pilot. See the dataset spec for
how partial episodes are indexed and censored without inventing safe labels.
