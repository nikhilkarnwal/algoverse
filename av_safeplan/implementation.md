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

If SimLingo is not stable enough for large runs, use Behavior Agent for pipeline debugging while SimLingo integration continues in parallel. Keep the central scientific comparison unchanged.
