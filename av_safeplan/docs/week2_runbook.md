# Week 2 dataset pilot

This workflow produces observed-policy future-risk samples, not alternative-action
labels. It does not train SimLingo. Dataset conversion uses Python 3.8+ and only
the standard library; no CARLA, CUDA or ML import/install is required.

## Build from existing recordings

From `av_safeplan` on EC2:

```bash
python3 scripts/build_week2_dataset.py \
  /home/ubuntu/av-safeplan-runtime/outputs/trajectories \
  /home/ubuntu/av-safeplan-runtime/outputs/datasets/week2-v1
```

On the Mac:

```bash
python3 scripts/build_week2_dataset.py \
  /Users/nikarn/Desktop/projects/MLStudy/algoverse_data/outputs/trajectories \
  /Users/nikarn/Desktop/projects/MLStudy/algoverse_data/outputs/datasets/week2-v1
```

Output must be outside the source root and not already exist. Use a new version
for reruns. Raw inputs are not overwritten. Partial mirrors can be indexed, but
missing images remain exclusions. Repeat `--episode relative/path/episode.jsonl`
to curate inputs rather than recursively discover them.

Pilot defaults: 3-second future horizon, 0.2-second anchor stride, seed 2026,
all negatives retained. Override with `--horizon-seconds`, `--stride-seconds`,
`--seed`, `--training-negative-keep`. Negative downsampling affects train only,
not validation/test/pilot, and saves selection probability and weight.

## Outputs and acceptance

| File | Purpose |
| --- | --- |
| `dataset_manifest.json` | Configuration, source hashes, converter revision/files, artifact hashes |
| `episodes.jsonl` | Backend, route, gaps, orphan images, recorder outcomes |
| `samples.jsonl` | RGB reference, current speed/base action, independent future targets and masks |
| `evidence.jsonl` | Unique event callbacks with occurrence/emission frames; not independent crash counts |
| `splits.json` | Whole-group assignments and grouping rationale |
| `quality_report.json` | Coverage, exclusions, label counts, readiness blockers |
| `collection_plan.json` | Bounded next-collection priorities |
| `review_queue.jsonl` | Unapproved review work items |
| `review_templates/` | Empty hash-bound review templates |

Only `sample.features` is the input whitelist. Events, applied controls, scenario
IDs, reviews, route IDs and privileged CARLA actor/light state are not features.
Speed is CARLA ground-truth until runtime sensor equivalence is verified. RGB is
stored by path/hash, not as a precomputed tensor. Images receive PNG header,
dimension and hash checks; complete decoding remains a loader preflight.

Exit zero means conversion succeeded, **not** that data is training-ready. The
pilot remains `pilot_not_training_ready` until reviewed targets, independent
coverage and a defined data-volume protocol exist. No target loss is enabled for
candidate or unknown labels. A timeout tail is never a safe negative.

## Human review format

Copy a generated template beside its original episode as `dataset_review.json`.
The `episode_sha256` must match exactly. Add intervals only after reviewing their
temporal scope; illustrative structure below is deliberately not approved:

```json
{
  "episode_sha256": "EXACT_HASH_FROM_TEMPLATE",
  "intervals": [{
    "hazard": "collision", "value": 0,
    "start_frame": 100, "end_frame": 180,
    "reviewed": false, "label_correct": null,
    "reviewer": null, "reviewed_at": null,
    "notes": "Review the full interval before approving."
  }]
}
```

Supported hazards are `collision` and `red_light_violation`. A negative requires
review coverage from anchor through horizon end. A positive needs its actual
event frame reviewed. Approval requires `reviewed=true`, `label_correct=true`,
reviewer and review timestamp. Stale hashes are rejected. Legacy Week 1 safe-row
reviews do not approve a future horizon. Near-miss/legacy encroachment windows
remain excluded; no automatic human-review substitute is generated.

## Grouping and reproducibility

Full-route bounding boxes expanded by 30m form connected groups within a map.
This over-groups conservatively rather than leaking overlapping route windows.
Unknown geometry merges with same-map groups; unknown map can merge across maps.
Policies and configuration variants remain together. Fewer than three groups
means `pilot`, not a manufactured three-way benchmark. Otherwise deterministic
hashing targets 70/15/15; tiny datasets may still lack one split and are flagged.

`--previous-splits /path/to/splits.json` rejects changes to existing assignments.
New bridge routes can require a new split version. The manifest records exact
source/implementation hashes. No normalization is fitted on held-out data.

Read-only verification of actual data (not a unit-test suite):

```bash
python3 scripts/verify_week2_dataset.py SOURCE_ROOT DATASET_DIR \
  --compare REBUILT_DATASET_DIR --output /absolute/new-verification-report.json
```

Add `--decode-images` in an existing environment with Pillow to fully decode
sample images. Nothing is installed by the auditor. It checks hashes, feature
whitelist, action/time alignment, loss masks and split consistency; it cannot
approve semantic label correctness.

## Bounded EC2 pilot

```bash
WEEK2_ROUTE_WALL_SECONDS=600 bash scripts/run_week2_collection_ec2.sh
```

Requires the existing pinned runtime and
`outputs/upstream/week1_town12_windowed_routes.xml`; no downloads occur. Routes
0, 1, 2 exercise lead braking, cross traffic and signalized compliance. The
corrected recorder saves real camera frame IDs and full route geometry.

The script requires 8 GiB free, refuses to interrupt an already-running CARLA,
limits each route to at most 600 wall seconds, and stops CARLA on exit. A timeout
stops the batch to avoid contaminating subsequent runs. New output is under
`outputs/trajectories/week2-pilot-*`; override with `WEEK2_OUTPUT=/absolute/new/path`.
The collection checker inspects criteria and logs for skipped scenarios even
when the evaluator exits zero. Scenario outcome failure is distinct from broken
data collection. Its `collection_report.json` is included in dataset provenance.
Use `WEEK2_ROUTE_IDS=1` to rerun only cross traffic. The seeded entry point applies
Python, NumPy, ScenarioRunner-provider and Traffic Manager seeds; pedestrians
are not explicitly seeded, so this is not a deterministic-replay certification.

Rebuild the dataset from full EC2 images after collection. These known routes
verify pipeline operation, not held-out diversity or red-light-positive coverage.

CARLA shutdown does not stop EC2 billing. The scripts neither delete raw data
nor stop the EC2 instance. Stop the instance separately when no other work needs it.

For one frozen-SimLingo cross-traffic pilot using the already installed model:

```bash
bash scripts/run_week2_simlingo_ec2.sh
```

This has a 900-second total simulator limit, offline model-cache use, automatic
CARLA shutdown, and bounded CPU video recovery afterward. `finalization.json`
records external termination separately from the original manifest. A process
exit or recovered video never implies official route completion.

## Recover a review video without another simulation

```bash
bash scripts/simlingo_ec2_run.sh python scripts/encode_episode_video.py \
  /absolute/episode/rgb /absolute/episode/recovered-review.mp4 --fps 20
```

Use a new output name; the encoder refuses overwrites. This CPU postprocessing
does not change the original route outcome. Partial JSONL records remain useful
for diagnosis, with orphan images counted and incomplete futures censored.

## Completed October 26 pilot (run IDs use UTC October 27)

Final EC2 dataset: `/home/ubuntu/av-safeplan-runtime/outputs/datasets/week2-curated-v1`.
Independent rebuild: `week2-curated-rebuild-v1`; read-only audit:
`week2-curated-verification.json`, all beside the final dataset.

- Five episodes, 2,492 raw records, 626 selected samples: 539 Behavior Agent and
  87 frozen SimLingo. All 626 sampled PNGs were fully decoded; samples, splits,
  and evidence hashes reproduced exactly. No source failures or orphan PNGs.
- Behavior runs: `week2-pilot-20261027T005740Z` (three routes) and
  `week2-pilot-20261027T010738Z` (seeded cross-traffic rerun). All four routes
  reached 100% completion. The two cross-traffic recordings each contain a
  collision; an unsafe driving outcome is not a collection failure.
- SimLingo: `week2-simlingo-20261027T011413Z`, route 1, 100% completion,
  driving score 100, no official infractions. `recording_integrity.json` verifies
  all 346 records, pass-through controls, sensor/world alignment, and 346 decoded
  MP4 frames at 20 fps. Semantic event labels are still unreviewed.
- Thirty collision-ahead sample targets are candidates, not 30 independent
  collisions. Zero targets are approved for supervised loss. No red-light
  positive was observed. Three geometry groups currently yield train/validation
  only; do not split related episodes to manufacture a test set.

The six engineering steps are implemented and exercised, but training-readiness
remains pending human interval review, independent coverage, and a data-volume
protocol. Do not infer relative policy performance from this tiny pilot or
assume ScenarioRunner and Leaderboard instantiate identical traffic interactions.
