"""Synchronized ego-camera trajectory recording for CARLA."""

from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Optional

from av_safeplan.settings import RecordingSettings


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
        record: Dict[str, Any] = {
            "world_frame": int(world_frame),
            "sensor_frame": int(image.frame),
            "timestamp_seconds": float(image.timestamp),
            "image": str(relative_image_path),
            "control": {
                "steer": float(control.steer),
                "throttle": float(control.throttle),
                "brake": float(control.brake),
                "hand_brake": bool(control.hand_brake),
                "reverse": bool(control.reverse),
            },
            "ego": {
                "location": {
                    "x": float(transform.location.x),
                    "y": float(transform.location.y),
                    "z": float(transform.location.z),
                },
                "rotation": {
                    "pitch": float(transform.rotation.pitch),
                    "yaw": float(transform.rotation.yaw),
                    "roll": float(transform.rotation.roll),
                },
                "velocity": {
                    "x": float(velocity.x),
                    "y": float(velocity.y),
                    "z": float(velocity.z),
                },
            },
        }
        with self.metadata_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
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
