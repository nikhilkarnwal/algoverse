# Week 2 dataset specification — v0.1

Status: specification and converter implemented under the October 26 Week 2
authorization. See `week2_runbook.md` for executable commands and acceptance
limitations. Numerical defaults are pilot settings, not a final research
protocol. No training is performed by the converter.

## 1. Prediction task and scope

One sample is a decision at simulation time `t` in one episode: predict whether
a collision or red-light violation occurs in `(t, t + H]`, conditioned on the
observation available at `t` and the frozen base policy's proposed action.
Keep two binary targets, not a mutually exclusive class: both hazards can occur.
This is observed-rollout risk under the recorded policy, not a counterfactual
estimate of what any alternative action would cause. A later action-selection
layer needs an additional, separately approved data/learning design.

Proposed starting configuration:

| Setting | Proposed value | Contract |
| --- | --- | --- |
| Future horizon `H` | 3.0 simulation seconds | Configurable per dataset build; persist it with every sample. |
| Observation history | 0 seconds (current frame only) | Optional later history must end at `t`; never pad from future frames. |
| Candidate sampling stride | 0.2 simulation seconds | Subsample decisions, not event detection; inspect all future event records. |
| Split proportions | 70% train, 15% validation, 15% test | Group-level goal, not guaranteed with a tiny pilot. |
| Split seed | 2026 | Persist alongside the immutable group assignment file. |

These defaults do not determine model architecture, class balancing, or an
intervention threshold. Those choices remain outside Step 1.

## 2. Source contract: what exists today

Use immutable source files; produce derived outputs separately. Paths in a
derived dataset must be relative to a declared source root, not EC2 hostnames.

| Source | Existing fields / role | Limitation |
| --- | --- | --- |
| `episode.jsonl` | `frame`, `timestamp_seconds`, `ego`, `nearby_actors`, `traffic_lights`, `route_state`, base/supervisor actions, `supervisor_intervened`, `events`, `seed`, `route`, `policy`, `scenario` | No explicit schema version; raw `sensors` and observation `metadata` are not serialized. |
| `trajectory.jsonl` | `world_frame`, `sensor_frame`, timestamp, `image`, `control`, ego pose/velocity | May be absent or frame-strided; does not contain future targets. |
| `rgb/frame_*.png` | Camera pixels referenced by trajectory records | Missing images are not black images. No-image runs are metadata-only. |
| `manifest.json` | Recorder/run configuration, route, seed, outcome and available counts | Fields differ across backends; `closed`/`completed` alone is not an official route pass. |
| Official criteria / `simulation_results.json` | Route completion and authoritative infractions | An aggregate failure/count is not a timestamped per-decision label. |
| `audit_queue.jsonl` | Run, category, center/window frames, event types, `audit.reviewed`, `audit.label_correct`, notes | Review is window-scoped; a reviewed example does not approve a whole episode. |

Adapters must identify the source backend/schema explicitly. The synthetic
macOS CPU path is suitable for pipeline development only and must be tagged
`synthetic`; never mix it into scientific training/evaluation silently.

## 3. Inference inputs versus privileged diagnostics

The initial proposed feature profile is `rgb_speed_base_action_v1`:

- Current aligned front RGB image, with camera identity, resolution, and
  preprocessing specification. Behavior Agent's `Center` camera and SimLingo's
  `rgb_0` are different sources; preserve that distinction.
- Current ego speed in metres/second. Existing `ego.speed_mps` comes from CARLA
  ground truth; record this source, and validate equivalence to a runtime speed
  sensor before claiming sensor-only deployment.
- Base action: `steer` in `[-1, 1]`, `throttle`/`brake` in `[0, 1]`, and boolean
  `hand_brake`/`reverse`. It is available after base inference, before supervision.

Nearby actor locations/velocities, ego-associated light state, and map/world
poses are privileged CARLA observations. Preserve them for labeling/debugging,
not as implicit sensor-only inputs. A privileged-state baseline must declare a
separate feature profile and cannot be presented as the deployable RGB model.
Route commands/plans and SimLingo latent embeddings are not recorded by the
shared episode logger; do not fabricate them from destination coordinates or
assume the model's embeddings are already available for training.

Exclude events, future states, official outcomes/scores, review decisions,
scenario names, run IDs, seeds, and route IDs from the model feature tensor.
Keep these in provenance or targets only. Do not use supervisor action or the
intervention flag as features: both are downstream of the decision being learned.

## 4. Frame alignment and temporal semantics

Join by `(episode_id, episode.frame == trajectory.world_frame)`, never by JSONL
line number or nearest image filename. Frames reset between episodes. Preserve
source timestamps and their basis (CARLA elapsed time versus Leaderboard game
time); compute `time_from_episode_start_seconds` within each episode only.

Require monotonic unique decision frames/times, finite numeric values, and a
documented fixed simulation delta or verified timing mapping. A matching image
must exist and have verified `sensor_frame == world_frame`. Legacy ScenarioRunner
recordings wrote the world frame into both trajectory frame fields;
equality in those files alone is not independent evidence of camera alignment.
The corrected adapter records actual sensor callback frames and declares this
in `sensor_timing`; the curated Week 2 pilot verifies those joins independently.
Record `alignment_status: verified | unverified | invalid` and the evidence.
Quarantine unverified samples from image-based scientific training until the
source sensor timing is established. Do not silently shift frames to make them fit.

All current policy paths collect state for frame `f` before the returned action
advances the next simulation tick. Interpret that action as the decision at
`f`, not the cause of collisions already observed at `f`. Events with
`event.frame <= f` are not future positives for sample `f`.

Collision callbacks can be logged on a later row. Scan the complete episode's
event lists, map each event's own frame to simulation time, and deduplicate by
a documented stable event identity. Missing/unmappable event frames are a
quality error, not a negative label. Retain both occurrence frame and emission
row frame. Red-light candidates currently record the trigger-exit detection
frame, not an independently measured stop-line crossing time; exact onset needs
review/official timing before promotion to a confirmed future target.

## 5. Labels, review, and censoring

Each hazard target contains `value: 0 | 1 | null`, `horizon_seconds`,
`status: candidate | confirmed | unknown | rejected`, `loss_mask: boolean`,
`evidence_ids`, `coverage_end_seconds`, and `reason_codes`.

- **Collision candidate:** a `collision` sensor event occurring in the future
  window. Retain other actor/type and impulse for audit; do not invent a severity
  cutoff. Repeated contact callbacks must not be mistaken for independent crashes.
- **Red-light candidate:** `red_light_violation` from the current monitor is a
  heuristic. Confirm the ego's actual crossing while its controlling signal is
  red using localized evidence. Nearby red signals are insufficient.
- **Negative candidate:** no event for that hazard over the entire future window,
  with verified continuous coverage and an operating detector. Absence of a JSON
  event, a zero aggregate score, or one safe frame alone is insufficient.
- **Confirmed:** a human review supports the hazard decision and its temporal
  scope, with retained evidence references. Official criteria corroborate the
  result but aggregate counts cannot localize events. Disagreements stay unknown
  pending resolution. Proposed default: only confirmed targets get `loss_mask=true`.
- **Near miss:** retain `near_miss` with TTC/closest-distance details as a separate
  heuristic/audit tag, never automatically convert it to collision-positive.
  Its review is independent of the two hazard targets. Unverified near misses
  are excluded from supervised sampling by default; retain them in quarantine.
- **Trigger entry:** `red_light_trigger_entry` is diagnostic, neither a violation
  nor a near-miss target. Legacy encroachment labels require explicit review.

For each hazard independently, if a confirmed event occurs before the available
future ends and within `H`, its positive is known even if the rest is truncated.
If no event is observed but coverage ends before `t + H`, set `value=null`,
`status=unknown`, `loss_mask=false`, reason `right_censored`. Never turn timeout,
route end, sensor failure, or missing tail frames into a safe future. Do not
extrapolate constant speed or assume safety after route completion. Internal
gaps invalidate a negative over the gap; retain localized confirmed positives
only when their onset and input alignment are still reliable.

The existing queue's category `negative` means a sampled row had no emitted
events, not that a 3-second future is reviewed safe. Map reviews by episode,
reviewed frame interval, hazard, and evidence hash. A negative target needs review
coverage through the whole horizon; a positive needs its actual event/onset
reviewed. Never infer reviewer identity/time where the old queue lacks them;
store null and retain the original review fields and source hash.

For pure base-policy risk, require pass-through controls throughout the future
window (to a positive onset, or through `H` for a negative). If an intervention
changes actions first, the counterfactual base-policy outcome is unknown; mask
it and record `intervened_rollout`. Preserve both proposed and applied controls.

## 6. Derived dataset layout and record contract

Outputs written by the implemented converter outside Git:

```text
dataset-v0.1/
  dataset_manifest.json
  episodes.jsonl
  samples.jsonl
  evidence.jsonl
  splits.json
  quality_report.json
```

| Record | Required contents |
| --- | --- |
| Dataset manifest | Schema/config version, creation time, converter revision (and dirty diff hash if applicable), source inventory hashes, feature profile, label/coverage policy, horizons, sampling/split settings, units, and known exclusions. |
| Episode | Stable `episode_id`, run/backend/policy identity, available checkpoint/source revisions, CARLA/map, route XML digest and original/prepared route IDs, scenario family/configuration, seed/weather if known, timing/camera metadata, source paths/hashes, recorder and official outcomes separately, usable interval, termination reason, alignment/coverage status, split group. |
| Sample | Stable `sample_id`, `episode_id`, anchor frame/time, history frame references if used, image reference/hash, allowed observed features, base/applied actions, intervention flag for provenance, two hazard targets, near-miss tag/review, split/group IDs, eligibility and reason codes. |
| Evidence | Stable evidence ID, source file/hash, occurrence/detection frame and time if known, emitted-row frame, event type/details, official criteria reference, original audit fields, reviewed scope, reviewer/time if known, and resolution. |
| Splits | Explicit episode-to-group-to-split assignments, grouping rationale, source inventory digest, seed, counts, and disjointness findings. |
| Quality report | Counts by policy/scenario/hazard/split/review status, candidate versus confirmed labels, masks/censoring reasons, missing data, timing/image failures, policy intervention exclusions, source duplicates, and readiness blockers. |

IDs must be deterministic from canonical source identity/content, not machine
absolute paths, directory enumeration order, or current time. Store null plus
an explicit missing-metadata reason for unavailable provenance. Unknown policy,
timing, or split identity blocks scientific eligibility; a partial source may
still be indexed for diagnostics. Paths must resolve under an approved source
root and must not traverse outside it. Keep raw evidence unchanged.

CARLA positions/distances use metres, velocities metres/second, rotations
degrees, and timestamps simulation seconds. Record the source world coordinate
convention; any ego-relative transformation must have a versioned definition.
No speed normalization or dataset statistics may be fitted on validation/test.

## 7. Leakage-resistant splits and sampling

Group before sampling windows. The same episode, overlapping windows, replay
duplicates, both policies, and all seed/weather/parameter variants of the same
route segment and conflict location belong to one split. Differently numbered
prepared routes can share a source segment; do not trust route ID alone.

Construct groups from canonical map/source route geometry, scenario trigger or
intersection location, and parent route lineage. Merge groups if route crops
overlap or share the same conflict location; keep these connected groups intact
across policies and reruns. Store configuration variants within a group, not as
a way to split the same geometry across train/test. Missing geometry/lineage
requires conservative manual grouping or exclusion, never random-frame fallback.

Freeze and version the assignment. Only then sample event-centered training
windows or downsample negatives. Record selection probabilities/weights; avoid
claiming natural hazard prevalence from a balanced sample. Validation/test must
retain a declared, consistent sampling population and policy-specific counts.
If only a few independent groups exist, report a pilot with no meaningful
held-out estimate rather than manufacturing three splits from adjacent frames.
Calibration must use validation or a dedicated held-out calibration subset,
never the final test set.

## 8. Existing evidence and next implementation gate

Week 1 is not made complete by this spec. Genuine near-miss review remains
pending. The older completed SimLingo baseline
`simlingo-route2-20261024T062511Z` has route evidence but no shared recorded
dataset; do not substitute aggregate metrics for samples. The later recorded
run `simlingo-route2-20261024T072202Z` was reported as timed out with 851 aligned
records, 852 PNGs, and an unfinished MP4. A future converter must independently
validate file counts and usable coverage, exclude orphan images, and censor
the tail. These reported counts do not establish label correctness.

The newer `week2-simlingo-20261027T011413Z` pilot completed with 346 aligned
records/images and 346 decoded video frames. It is included in the curated
five-episode dataset, while the old timed-out run remains diagnostic only.
Official results are preserved with hashes as aggregate corroboration, not as
timestamped labels. The curated dataset has 626 samples from 2,492 raw records;
all sampled PNGs decode and an independent build reproduces samples/splits.

The approved Week 2 implementation now includes source adapters, the converter,
quality report and bounded pilot collection. Assess actual usable samples before training.
Scientific readiness requires verified timing, sufficient reviewed hazard
coverage, non-overlapping groups, and an explicit review of data availability.
Open choices: approve/change the 3-second horizon and feature profile; decide
whether weak-label training is a separate experiment; choose data-volume and
class-coverage targets after the pilot report; define any future alternative-
action training objective. No choices here authorize new collection or training.
