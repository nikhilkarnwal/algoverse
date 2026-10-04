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

## Colab Pro setup

Colab's managed runtime uses a newer system Python than SimLingo. Do not install the pinned SimLingo stack into Colab's system interpreter. The Colab setup creates an isolated Python 3.8 environment with micromamba and exposes it through a command wrapper.

First select a GPU runtime in Colab, clone this repository, and run:

```bash
git clone https://github.com/nikhilkarnwal/algoverse.git /content/algoverse
cd /content/algoverse/av_safeplan
chmod +x scripts/*.sh
./scripts/setup_colab.sh
```

The setup script:

- Checks that an NVIDIA GPU is attached.
- Installs the Linux libraries required by CARLA.
- Creates an isolated Python 3.8.18 environment.
- Installs the CUDA 12.1 PyTorch 2.2 stack before other dependencies.
- Builds Flash Attention against that exact stack.
- Clones SimLingo at the pinned Git revision.
- Downloads CARLA 0.9.15, which contains the Town12 map used by this project.
- Downloads only the inference checkpoint and Hydra configuration rather than the training optimizer shards.
- Caches InternVL2-1B.
- Writes the local `.env` consumed by the project scripts.

Run project Python commands through the wrapper:

```bash
./scripts/colab_run.sh python scripts/verify_stack.py
```

Start the CARLA server in off-screen mode and perform live verification:

```bash
./scripts/start_carla_colab.sh
./scripts/colab_run.sh python scripts/verify_stack.py --live
./scripts/colab_run.sh python scripts/smoke_behavior_agent.py --steps 50
```

To start CARLA and record a complete Behavior Agent trajectory in one command:

```bash
./scripts/run_behavior_trajectory_colab.sh --steps 200
```

Each run creates a separate directory containing ordered RGB images and frame-aligned vehicle state/control metadata:

```text
/content/av_safeplan/outputs/trajectories/
  Town12_seed2026_20261004T120000Z/
    rgb/
      frame_000123.png
      frame_000124.png
    trajectory.jsonl
```

Colab's local filesystem disappears with the runtime. To keep recordings, mount Google Drive and set the output root before running setup (or edit the generated `.env`):

```bash
export AV_SAFEPLAN_OUTPUT_ROOT=/content/drive/MyDrive/av_safeplan_runs
./scripts/setup_colab.sh
```

CARLA and the model downloads are large. To reuse downloaded archives and the Hugging Face cache from a mounted Google Drive directory, set `AV_SAFEPLAN_CACHE_ROOT` before setup. Runtime execution should still use `/content` where possible because direct reads from Drive can be slower. Set `AV_SAFEPLAN_EXTERNAL_ROOT` to a Drive directory only if persistent extracted assets are more important than runtime speed.

```bash
export AV_SAFEPLAN_CACHE_ROOT=/content/drive/MyDrive/av_safeplan_cache
./scripts/setup_colab.sh
```

Optional setup controls:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AV_SAFEPLAN_DOWNLOAD_CARLA` | `1` | Set to `0` when CARLA is already available. |
| `AV_SAFEPLAN_DOWNLOAD_ADDITIONAL_MAPS` | `0` | Set to `1` only when optional maps outside the base package are needed. |
| `AV_SAFEPLAN_DOWNLOAD_MODELS` | `1` | Set to `0` when model assets are already available. |
| `AV_SAFEPLAN_INSTALL_FLASH_ATTN` | `1` | Set to `0` only for environment diagnosis. |
| `AV_SAFEPLAN_KEEP_DOWNLOAD_ARCHIVES` | `0` | Keep large CARLA archives after successful extraction. |
| `AV_SAFEPLAN_CARLA_MIN_FREE_GB` | `30` | Minimum free space required before CARLA extraction. |
| `AV_SAFEPLAN_COLAB_ROOT` | `/content/av_safeplan` | Runtime environment and cache root. |
| `AV_SAFEPLAN_EXTERNAL_ROOT` | `/content/av_safeplan/external` | CARLA, SimLingo, and model location. |
| `AV_SAFEPLAN_OUTPUT_ROOT` | `/content/av_safeplan/outputs/trajectories` | Recorded RGB trajectories and metadata. |

Colab hardware and runtime lifetimes are not guaranteed. Save experiment outputs to Drive or another persistent store before the runtime terminates.

If CARLA extraction was interrupted, rerun `./scripts/setup_colab.sh`. The installer now validates or resumes the archive and extracts through a separate staging directory. It will not delete an incomplete directory automatically; inspect and remove or rename the path printed in the error first. Keep extracted runtime files under `/content`; Google Drive is better used for download caches and recorded trajectories.

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

The runner loads Town12, enables synchronous execution at 20 Hz, seeds the Traffic Manager, spawns a deterministic ego vehicle, and executes a short route. By default, a rigid RGB camera saves one PNG per simulator tick plus a `trajectory.jsonl` record containing the matching frame ID, timestamp, ego pose, velocity, and control command. Original world settings are restored and all spawned actors are destroyed even on failure.

For a shorter diagnostic run:

```bash
python scripts/smoke_behavior_agent.py --steps 50
```

Choose an output directory or a stable run name with `--output-dir` and `--run-name`. Use `--no-images` for a route-only diagnostic. Camera resolution, pose, field of view, and frame stride are configured under `recording` in `config/stack.yaml`.

## Design boundaries

- Versions and upstream revisions live in one manifest.
- Machine-specific paths come only from environment variables.
- Heavy framework imports occur only inside verification or execution functions.
- CARLA synchronous state is restored on exit.
- Weights, CARLA distributions, logs, and generated datasets stay outside Git.

The common Behavior Agent/SimLingo policy interface belongs to the next implementation task.
