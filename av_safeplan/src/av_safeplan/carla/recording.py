"""Synchronized ego-camera trajectory recording for CARLA."""

from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Mapping, Optional

from av_safeplan.settings import RecordingSettings


def build_trajectory_record(
    world_frame: int,
    sensor_frame: int,
    timestamp_seconds: float,
    image_path: Path,
    control: Mapping[str, Any],
    location: Mapping[str, float],
    rotation: Mapping[str, float],
    velocity: Mapping[str, float],
) -> Dict[str, Any]:
    """Build the shared trajectory schema used by real and synthetic runs."""
    return {
        "world_frame": int(world_frame),
        "sensor_frame": int(sensor_frame),
        "timestamp_seconds": float(timestamp_seconds),
        "image": str(image_path),
        "control": {
            "steer": float(control["steer"]),
            "throttle": float(control["throttle"]),
            "brake": float(control["brake"]),
            "hand_brake": bool(control["hand_brake"]),
            "reverse": bool(control["reverse"]),
        },
        "ego": {
            "location": {axis: float(location[axis]) for axis in ("x", "y", "z")},
            "rotation": {axis: float(rotation[axis]) for axis in ("pitch", "yaw", "roll")},
            "velocity": {axis: float(velocity[axis]) for axis in ("x", "y", "z")},
        },
    }


class TrajectoryMetadataWriter:
    """Append trajectory records without depending on a simulator backend."""

    def __init__(self, metadata_path: Path):
        self.metadata_path = metadata_path
        self.metadata_path.touch(exist_ok=False)
        self.records_written = 0

    def append(self, record: Mapping[str, Any]) -> None:
        with self.metadata_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(record), sort_keys=True) + "\n")
        self.records_written += 1


def create_run_directory(output_root: Path, map_name: str, seed: int, run_name: Optional[str]) -> Path:
    """Create a unique directory for one trajectory recording."""
    if run_name:
        if Path(run_name).name != run_name or run_name in {".", ".."}:
            raise ValueError("Run name must be a single directory name")
        directory_name = run_name
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        directory_name = "{}_seed{}_{}".format(map_name, seed, timestamp)
    run_directory = output_root / directory_name
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "rgb").mkdir()
    return run_directory


class RgbTrajectoryRecorder:
    """Attach an RGB camera and persist frame-aligned images and metadata."""

    def __init__(
        self,
        world: Any,
        ego_vehicle: Any,
        settings: RecordingSettings,
        run_directory: Path,
    ):
        self.world = world
        self.ego_vehicle = ego_vehicle
        self.settings = settings
        self.run_directory = run_directory
        self.image_directory = run_directory / "rgb"
        self.metadata_path = run_directory / "trajectory.jsonl"
        self._metadata_writer = TrajectoryMetadataWriter(self.metadata_path)
        if settings.frame_stride < 1:
            raise ValueError("Recording frame_stride must be at least 1")
        if settings.image_width < 1 or settings.image_height < 1:
            raise ValueError("Recording image dimensions must be positive")
        self._queue = Queue()
        self._sensor = None
        self._saved_images = 0

    @property
    def saved_images(self) -> int:
        return self._saved_images

    def start(self) -> None:
        import carla

        blueprint = self.world.get_blueprint_library().find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", str(self.settings.image_width))
        blueprint.set_attribute("image_size_y", str(self.settings.image_height))
        blueprint.set_attribute("fov", str(self.settings.field_of_view))
        transform = carla.Transform(
            carla.Location(
                x=self.settings.camera.x,
                y=self.settings.camera.y,
                z=self.settings.camera.z,
            ),
            carla.Rotation(
                pitch=self.settings.camera.pitch,
                yaw=self.settings.camera.yaw,
                roll=self.settings.camera.roll,
            ),
        )
        self._sensor = self.world.spawn_actor(
            blueprint,
            transform,
            attach_to=self.ego_vehicle,
            attachment_type=carla.AttachmentType.Rigid,
        )
        self._sensor.listen(self._queue.put)

    def save_frame(self, world_frame: int, control: Any, timeout_seconds: float = 10.0) -> None:
        """Save the camera image matching a synchronous CARLA world frame."""
        if world_frame % self.settings.frame_stride != 0:
            self._discard_until(world_frame, timeout_seconds)
            return

        image = self._next_image(world_frame, timeout_seconds)
        image_name = "frame_{:06d}.png".format(world_frame)
        relative_image_path = Path("rgb") / image_name
        image.save_to_disk(str(self.run_directory / relative_image_path))

        transform = self.ego_vehicle.get_transform()
        velocity = self.ego_vehicle.get_velocity()
        record = build_trajectory_record(
            world_frame=world_frame,
            sensor_frame=image.frame,
            timestamp_seconds=image.timestamp,
            image_path=relative_image_path,
            control={
                "steer": control.steer,
                "throttle": control.throttle,
                "brake": control.brake,
                "hand_brake": control.hand_brake,
                "reverse": control.reverse,
            },
            location={
                "x": transform.location.x,
                "y": transform.location.y,
                "z": transform.location.z,
            },
            rotation={
                "pitch": transform.rotation.pitch,
                "yaw": transform.rotation.yaw,
                "roll": transform.rotation.roll,
            },
            velocity={"x": velocity.x, "y": velocity.y, "z": velocity.z},
        )
        self._metadata_writer.append(record)
        self._saved_images += 1

    def _next_image(self, world_frame: int, timeout_seconds: float) -> Any:
        while True:
            try:
                image = self._queue.get(timeout=timeout_seconds)
            except Empty as error:
                raise RuntimeError(
                    "Timed out waiting for RGB image at CARLA frame {}".format(world_frame)
                ) from error
            if image.frame < world_frame:
                continue
            if image.frame > world_frame:
                raise RuntimeError(
                    "RGB camera skipped frame {} and returned {}".format(world_frame, image.frame)
                )
            return image

    def _discard_until(self, world_frame: int, timeout_seconds: float) -> None:
        self._next_image(world_frame, timeout_seconds)

    def close(self) -> None:
        if self._sensor is not None:
            self._sensor.stop()
            if self._sensor.is_alive:
                self._sensor.destroy()
            self._sensor = None

    def __enter__(self) -> "RgbTrajectoryRecorder":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()
