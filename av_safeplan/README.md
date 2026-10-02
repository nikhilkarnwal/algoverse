# AV SafePlan

Modular infrastructure for studying calibrated multi-hazard safety supervision in CARLA.

This milestone pins the CARLA/SimLingo runtime and provides environment validation plus a Behavior Agent smoke route. CARLA, SimLingo, and model weights remain external to this repository.

## Pinned stack

| Component | Version or revision |
| --- | --- |
| CARLA | `0.9.15` |
| Python | `3.8.18` |
| PyTorch | `2.2.0` |
| Torchvision | `0.17.0` |
| Transformers | `4.46.3` |
| Flash Attention | `2.7.0.post2` |
| SimLingo source | `743b243afd6cf5ff51b9fa1f8cac86f22d569684` |
| SimLingo checkpoint | `epoch=013.ckpt/pytorch_model.pt` |

The machine-readable source of truth is [`config/stack.yaml`](config/stack.yaml).

## Platform expectations

Closed-loop SimLingo evaluation requires Linux with an NVIDIA GPU. The environment uses CUDA 12.1 packages. CARLA and the SimLingo checkpoint are large external assets and should live outside the Git checkout.

## 1. Prepare external dependencies

Install CARLA 0.9.15 and clone SimLingo at the pinned revision:

```bash
git clone https://github.com/RenzKa/simlingo.git /opt/simlingo
git -C /opt/simlingo checkout 743b243afd6cf5ff51b9fa1f8cac86f22d569684
```

Download the official SimLingo `epoch=013` checkpoint and InternVL2-1B model into a persistent model directory. Do not commit either asset.

## 2. Create the environment

```bash
cd av_safeplan
./scripts/bootstrap_environment.sh
conda activate av-safeplan-simlingo
```

The bootstrap script creates the pinned environment, installs Flash Attention after PyTorch, and installs this package in editable mode.

## 3. Configure paths

```bash
cp .env.example .env
```

Edit `.env`, then export it in the current shell:

```bash
set -a
source .env
set +a
```

Required variables:

- `CARLA_ROOT`
- `SIMLINGO_ROOT`
- `SIMLINGO_CHECKPOINT`
- `HF_HOME`

Connection values can be overridden with `CARLA_HOST`, `CARLA_PORT`, and `CARLA_TRAFFIC_MANAGER_PORT`.

## 4. Verify the offline stack

```bash
python scripts/verify_stack.py
```

Use `--json` for machine-readable output. The verifier checks exact dependency versions, CUDA, external paths, the SimLingo revision, the checkpoint, and Behavior Agent imports. Heavy imports are lazy so all setup failures are reported together.

## 5. Verify a running CARLA server

Start CARLA 0.9.15, then run:

```bash
python scripts/verify_stack.py --live
```

The live check compares CARLA client/server versions and verifies that Town12 is available.

## 6. Run the Behavior Agent smoke route

```bash
python scripts/smoke_behavior_agent.py
```

The runner loads Town12, enables synchronous execution at 20 Hz, seeds the Traffic Manager, spawns a deterministic ego vehicle, and executes a short route. Original world settings are restored and the ego actor is destroyed even on failure.

For a shorter diagnostic run:

```bash
python scripts/smoke_behavior_agent.py --steps 50
```

## Design boundaries

- Versions and upstream revisions live in one manifest.
- Machine-specific paths come only from environment variables.
- Heavy framework imports occur only inside verification or execution functions.
- CARLA synchronous state is restored on exit.
- Weights, CARLA distributions, logs, and generated datasets stay outside Git.

The common Behavior Agent/SimLingo policy interface belongs to the next implementation task.
