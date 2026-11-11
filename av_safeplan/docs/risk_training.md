# Risk predictor: offline preparation and gated training

This is supervised prediction of **observed frozen-SimLingo rollout risk** in
the next three simulation seconds. It is not PPO, SimLingo fine-tuning, or
counterfactual action scoring. The two outputs are independent probabilities:
collision (any actor category) and red-light violation.

## Current data and review boundary

The October 29 v2 campaign has six completed episodes: runs 03, 04, 05, 07, 11,
12. The six incomplete episodes are preserved but excluded from this initial
training index. Completion does not mean safe driving or correct labels.
The frozen groups remain train/validation/test; no random frame splitting.

There are 729 candidate windows from 2,906 aligned records. Training has 31
collision-positive and 15 red-light-positive candidate windows (overlapping
windows/callbacks are not independent events). Completed validation and test
routes have no positive candidates for either hazard. These are inventory
counts, not model evaluation or confirmed labels. Tail windows are censored.
No label is silently promoted: all supervised masks remain false until scoped,
hash-bound review. Post-event/intervened windows and invalid inputs are excluded.
Near-miss review waiver does not approve either hazard label.

Full training refuses to proceed without eligible **confirmed positives and
negatives for each hazard in both train and validation**. More validation
coverage is needed without moving existing groups or using test results to
choose routes, thresholds, or hyperparameters. Six routes remain only a pilot.

## Environment (separate from simulator)

Use Python 3.10–3.12. The simulator package's Python 3.8 constraint is unchanged;
these entry scripts import the source tree directly, so do not install the
whole project with `pip install -e .` in this environment.

```bash
python3.12 -m venv .venv-risk
.venv-risk/bin/python -m pip install -r environments/requirements-risk-training.txt
```

The pinned requirements work for local CPU smoke checking. On EC2 use a separate
environment too; do not replace the SimLingo environment or install a CUDA
compiler. No EC2 installation/run is performed by these commands unless run
there explicitly. Validate a compatible PyTorch GPU wheel and `torch.cuda.is_available()`
before selecting `--device cuda`. Deterministic CUDA runs also need
`CUBLAS_WORKSPACE_CONFIG=:4096:8` set before Python starts.

## Build the dataset

`SOURCE` is the extracted campaign directory containing `campaign_status.json`,
`manifest.json` and completed run folders. Output must be outside that directory
and must not already exist.

```bash
python scripts/prepare_campaign_training.py "$SOURCE" "$DATASET"
```

The converter checks episode and route hashes, official completion, sensor
alignment and frozen geometry/group disjointness. It generates samples, source
inventory, evidence, coverage reports, review templates and frozen splits.
After review, rebuild to a **new version** using the same campaign assignments;
do not edit masks directly in `samples.jsonl`.

## Engineering smoke check (allowed before review)

```bash
python scripts/train_risk_predictor.py "$DATASET" "$SOURCE" "$SMOKE_OUTPUT" \
  --mode smoke --device cpu --max-seconds 120
```

Uses up to four aligned training inputs and **synthetic alternating targets**,
not unreviewed candidate labels. Runs exactly two small-CNN optimization steps,
checks finite loss/gradients, saves optimizer/scheduler/model state, and verifies
checkpoint reload predictions. Does not evaluate validation or test. Smoke
checkpoints are marked engineering-only and rejected by inference/evaluation.
The smoke check is an execution check, not a unit-test suite or performance result.

## Reviewed pilot training (blocked on current data)

```bash
python scripts/train_risk_predictor.py "$DATASET" "$SOURCE" "$TRAIN_OUTPUT" \
  --mode train --device cpu --epochs 10 --batch-size 16 --max-seconds 600
```

Starts from ImageNet ResNet18 (downloads weights only after label gates pass),
freezes its encoder and BatchNorm, and learns a small RGB+speed+base-action head.
Full-frame resize to 128x256, fixed ImageNet normalization, speed divided by
30 m/s, and ordered steer/throttle/brake/hand-brake/reverse are shared with
inference. No crops/flips that could remove signals or alter steering semantics.
No privileged locations, events, outcomes, routes or labels enter the feature tensor.

AdamW, masked BCE, gradient clipping and cosine scheduling are implemented.
Seed/config/data/split/code hashes and metrics are recorded; outputs refuse
overwrite. `last.pt` and best validation-BCE `best.pt` contain training state.
No automatic resume, hyperparameter search, class resampling or calibration is
performed. Budget overruns abort; the last finished epoch checkpoint is preserved.
This initial recipe is a baseline, not evidence of adequate statistical power.

## Evaluation and later closed-loop integration

```bash
python scripts/evaluate_risk_predictor.py "$TRAIN_OUTPUT/best.pt" \
  "$DATASET" "$SOURCE" "$VALIDATION_REPORT"
```

Reports masked BCE, Brier score, average precision, AUROC and confusion counts
at a diagnostic 0.5 threshold. Ranking metrics are null when a class is missing.
Test evaluation requires `--split test --final-test` and should run only after
model selection is frozen; it has **not** been run. Current dataset hashes must
match the trained checkpoint.

`ShadowRiskPredictor.predict(PIL_RGB, speed_mps, base_action)` is the prepared
runtime boundary. After base SimLingo inference, pass the aligned image, speed
and proposed control; log the returned risks alongside that decision. It returns
no control override. Runtime speed sensor equivalence, callback integration,
latency measurement and live CARLA validation are future gates, not implemented
deployment claims. Smoke weights are refused. Reviewed pilot weights remain
uncalibrated and non-deployable.

Before any active supervisor: review labels, obtain appropriate independent
validation coverage, freeze/calibrate thresholds on validation only, then
validate shadow mode. An alternative-action selector needs counterfactual data
and an additional design; these observed-rollout scores cannot justify choosing
an unseen action.
