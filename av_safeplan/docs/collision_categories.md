# Collision-category metadata and near-miss policy

Dataset schema v2 adds `collision_metadata` outside `features`, classified collision
evidence, and `collision_coverage.json`. There are still only two binary targets.
Raw observations, event identities, source reviews and existing data are not rewritten.

Mapping v1: `vehicle.*` → vehicle; `walker.pedestrian.*` → pedestrian;
`static.prop.*` → static_object; anything else → unknown. Parked vehicles stay
vehicle. Known bicycle blueprints retain subtype bicycle within vehicle and must
not be presented as pedestrian evidence. Raw actor type is always preserved.
Automatic category assignment is not a human-reviewed label.

Each sample retains all future collision categories and their evidence IDs. Mixed
windows are counted in multiple category cells, so totals are not additive. A
combined positive target confirmed from its first onset does not approve later
events of another category; coverage reports confirmed first-onset windows only.

Coverage is zero-filled by category × policy × train/validation/test/pilot and
reports callbacks, unique episode/actor contacts, episodes, geometric groups,
positive/negative/unknown windows, confirmed windows, enabled losses and exclusions.
Callbacks and unique actors are not independent crash counts. Category encounter
metadata for safe windows is currently unavailable: negatives remain unknown
category rather than inferring a pedestrian/obstacle encounter from no collision.
Coverage blockers explicitly retain this gap. Adding verified encounter context
is a separate follow-up; scenario titles alone cannot confirm the interaction.

## User-authorized near-miss waiver

Use `--near-miss-policy waive_manual_review` for the newly authorized policy.
The default `exclude` preserves previous behavior for reproduction. Waiver means
near-miss flags no longer veto independently reviewed collision/red-light target
losses. Flags remain heuristic, `human_reviewed: false`, semantic correctness
unverified. No near-miss positive target is introduced and no legacy human audit
queue is marked correct. Legacy red-light encroachment still blocks eligibility.

Human review of actual collision/red-light labels, camera alignment, interventions,
post-event exclusion, source failures and truncated futures retain their existing
rules. An interrupted construction episode remains excluded by the failed official
collection-integrity gate; this policy change does not silently admit it.

Generate a fresh output directory; never overwrite previous dataset versions.
No training or simulator is needed to generate and audit these reports.
