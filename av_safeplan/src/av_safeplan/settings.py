"""Typed loading and validation for the AV SafePlan stack manifest."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass(frozen=True)
class CarlaSettings:
    version: str
    host: str
    port: int
    traffic_manager_port: int
    timeout_seconds: float
    map_name: str
    synchronous: bool
    fixed_delta_seconds: float
    seed: int


@dataclass(frozen=True)
class CheckpointSettings:
    repository: str
    revision: str
    relative_path: str
    minimum_size_bytes: int


@dataclass(frozen=True)
class SimLingoSettings:
    repository: str
    revision: str
    root: Optional[Path]
    checkpoint: Optional[Path]
    checkpoint_spec: CheckpointSettings
    vision_model_repository: str


@dataclass(frozen=True)
class RuntimeSettings:
    python: str
    torch: str
    torchvision: str
    transformers: str
    flash_attn: str
    cuda_required: bool


@dataclass(frozen=True)
class SmokeSettings:
    steps: int
    behavior: str


@dataclass(frozen=True)
class CameraSettings:
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float


@dataclass(frozen=True)
class RecordingSettings:
    enabled: bool
    output_root: Path
    frame_stride: int
    image_width: int
    image_height: int
    field_of_view: float
    camera: CameraSettings


@dataclass(frozen=True)
class StackSettings:
    project: str
    carla: CarlaSettings
    simlingo: SimLingoSettings
    runtime: RuntimeSettings
    smoke: SmokeSettings
    recording: RecordingSettings
    carla_root: Optional[Path]
    model_cache: Optional[Path]


def _environment_path(variable: str) -> Optional[Path]:
    value = os.environ.get(variable)
    return Path(value).expanduser().resolve() if value else None


def _required(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError("Missing required configuration key: {}".format(key))
    return mapping[key]


def load_stack(path: Path) -> StackSettings:
    """Load the stack manifest and apply supported environment overrides."""
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("Stack configuration must be a YAML mapping")

    carla_data = _required(data, "carla")
    simlingo_data = _required(data, "simlingo")
    checkpoint_data = _required(simlingo_data, "checkpoint")
    runtime_data = _required(data, "runtime")
    path_data = _required(data, "paths")
    smoke_data = _required(data, "smoke")
    recording_data = _required(data, "recording")
    camera_data = _required(recording_data, "camera")

    host = os.environ.get("CARLA_HOST", str(_required(carla_data, "host")))
    port = int(os.environ.get("CARLA_PORT", _required(carla_data, "port")))
    traffic_manager_port = int(os.environ.get(
        "CARLA_TRAFFIC_MANAGER_PORT", _required(carla_data, "traffic_manager_port")
    ))
    checkpoint = CheckpointSettings(
        repository=str(_required(checkpoint_data, "repository")),
        revision=str(_required(checkpoint_data, "revision")),
        relative_path=str(_required(checkpoint_data, "relative_path")),
        minimum_size_bytes=int(_required(checkpoint_data, "minimum_size_bytes")),
    )
    configured_output_root = os.environ.get(
        "AV_SAFEPLAN_OUTPUT_ROOT", str(_required(recording_data, "output_root"))
    )

    return StackSettings(
        project=str(_required(data, "project")),
        carla=CarlaSettings(
            version=str(_required(carla_data, "version")),
            host=host,
            port=port,
            traffic_manager_port=traffic_manager_port,
            timeout_seconds=float(_required(carla_data, "timeout_seconds")),
            map_name=str(_required(carla_data, "map")),
            synchronous=bool(_required(carla_data, "synchronous")),
            fixed_delta_seconds=float(_required(carla_data, "fixed_delta_seconds")),
            seed=int(_required(carla_data, "seed")),
        ),
        simlingo=SimLingoSettings(
            repository=str(_required(simlingo_data, "repository")),
            revision=str(_required(simlingo_data, "revision")),
            root=_environment_path(str(_required(path_data, "simlingo_root_env"))),
            checkpoint=_environment_path(str(_required(path_data, "checkpoint_env"))),
            checkpoint_spec=checkpoint,
            vision_model_repository=str(_required(
                _required(simlingo_data, "vision_model"), "repository"
            )),
        ),
        runtime=RuntimeSettings(
            python=str(_required(runtime_data, "python")),
            torch=str(_required(runtime_data, "torch")),
            torchvision=str(_required(runtime_data, "torchvision")),
            transformers=str(_required(runtime_data, "transformers")),
            flash_attn=str(_required(runtime_data, "flash_attn")),
            cuda_required=bool(_required(runtime_data, "cuda_required")),
        ),
        smoke=SmokeSettings(
            steps=int(_required(smoke_data, "steps")),
            behavior=str(_required(smoke_data, "behavior")),
        ),
        recording=RecordingSettings(
            enabled=bool(_required(recording_data, "enabled")),
            output_root=Path(configured_output_root).expanduser(),
            frame_stride=int(_required(recording_data, "frame_stride")),
            image_width=int(_required(recording_data, "image_width")),
            image_height=int(_required(recording_data, "image_height")),
            field_of_view=float(_required(recording_data, "field_of_view")),
            camera=CameraSettings(
                x=float(_required(camera_data, "x")),
                y=float(_required(camera_data, "y")),
                z=float(_required(camera_data, "z")),
                pitch=float(_required(camera_data, "pitch")),
                yaw=float(_required(camera_data, "yaw")),
                roll=float(_required(camera_data, "roll")),
            ),
        ),
        carla_root=_environment_path(str(_required(path_data, "carla_root_env"))),
        model_cache=_environment_path(str(_required(path_data, "model_cache_env"))),
    )
