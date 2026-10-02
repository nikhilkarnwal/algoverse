# Implementation Plan

## Week 1 — Environment, Policy Interfaces, Scenarios, and Labels

- Pin the CARLA version and dependency stack required for the selected SimLingo checkpoint; verify Behavior Agent in the same environment where feasible.
- Bring up Town12 in synchronous mode with a fixed simulation step and deterministic seed handling.
- Implement a common base-policy interface: observation → steering, throttle, and brake.
- Integrate Behavior Agent and validate reproducible closed-loop routes.
- Integrate the frozen SimLingo driving policy behind the same policy/control interface.
- Build a shared logger for:
  - Ego state
  - Nearby actors
  - Traffic lights
  - Route state
  - Base-policy action
  - Safety-supervisor action
  - Collision and red-light events
  - Seed, route, policy, and scenario parameters
- Implement collision and red-light event-label logic.
- Manually audit positive, negative, and near-miss episodes.
- Build controlled scenario families without adding more hazard categories.

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

If SimLingo is not stable enough for large runs, use Behavior Agent for pipeline debugging while SimLingo integration continues in parallel. Keep the central scientific comparison unchanged.
