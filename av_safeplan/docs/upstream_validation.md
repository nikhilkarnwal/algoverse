# Two-scenario upstream validation

This diagnostic runs existing `PedestrianCrossing` and `ConstructionObstacle`
implementations from pinned ScenarioRunner. It uses official Town12 Leaderboard
route entries selected by `config/week2_upstream_validation.yaml`, without a
custom behavior override. It is not a full collection campaign or held-out test.

```bash
bash scripts/run_week2_upstream_validation_ec2.sh
```

The launcher refuses an existing CARLA container, requires 8 GiB free, creates a
new timestamped directory, selects scenarios, traces bounded route windows, then
runs one Behavior Agent episode per family. Startup and route preparation each
have a 300-second cap; each episode has a 600-second cap. No automatic reruns.
Any failed process or failed collection-integrity check stops the batch. An exit
trap saves the CARLA log and stops the container. It does not stop the EC2 instance.

Outputs are under `outputs/trajectories/week2-upstream-validation-TIMESTAMP/`:

- selection-config.yaml, selection.json, full-routes.xml, routes.xml,
  route-windows.json: upstream provenance and derived route windows.
- route-0.log and route-1.log plus exit-code files: evaluator execution evidence.
- criteria/route-0 and criteria/route-1: official results.
- telemetry/week2-upstream-0 and telemetry/week2-upstream-1: raw records and PNGs.
- collection_report.json: structural integrity, not semantic approval.

Route 0 is pedestrian and route 1 is construction; these numeric IDs are local
to this run, not the earlier cross-traffic pilot's category mapping.

After execution, verify actual actor presence, scenario triggering, event timing
and videos in addition to process success. A route result alone does not prove
that the intended pedestrian or construction encounter occurred. A collision-free
run can provide negative candidates, but complete future intervals still need
scoped review. Do not promote automatic labels or add these diagnostics to a
held-out dataset without separately reviewing geometry/splits and provenance.

## First execution: week2-upstream-validation-20261027T064014Z

Pedestrian recording completed (654 frames, 100% route completion), but the
official driving result failed with one counted collision and lane departure.
Sensor callbacks identify two pedestrian contacts at video 15.80s and 15.95s;
their difference from the official count remains explicit for review.

Construction contacted a static warning prop at video 21.35s and remained
effectively blocked for much of the run. It hit the 600-second wall cap with
4,020 records and no final official result. Later vehicle/cone contacts make it
a mixed-category episode. Its video was recovered without rewriting raw logs;
external finalization records exit 124. This is incomplete diagnostic evidence,
not a successful validation. No automatic rerun was performed.

Both videos fully decoded (654 and 4,020 frames); every frame/control join passed.
Human label review and construction termination investigation remain pending.
The launcher now reports every attempted route on a timeout as well as on success.
