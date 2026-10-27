"""Shared episode evidence around a Leaderboard-owned policy and sensors."""

from collections import Counter
import json
from pathlib import Path

from av_safeplan.carla.observations import collect_observation
from av_safeplan.carla.recording import TrajectoryMetadataWriter, build_trajectory_record
from av_safeplan.safety.events import SafetyEventMonitor
from av_safeplan.safety.supervisor import PassthroughSupervisor
from av_safeplan.telemetry.episode import EpisodeLogger


class LeaderboardEpisodeRecorder:
    """Record existing front-camera frames without changing the sensor contract.

    The caller owns policy and world ticks; this object owns only its collision
    sensor and output files. Official route scores remain separate evidence.
    """

    def __init__(self, directory, world, ego, destination, route, seed, images=True):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.world, self.ego, self.destination = world, ego, destination
        self.map_name = world.get_map().name
        self.route, self.seed = dict(route), int(seed)
        self.images = images
        self.supervisor = PassthroughSupervisor()
        self.monitor = SafetyEventMonitor(world, ego)
        self.logger = EpisodeLogger(self.directory / "episode.jsonl", seed=seed,
                                   route=route, policy_name="simlingo",
                                   scenario={"backend": "leaderboard"})
        self.trajectory = TrajectoryMetadataWriter(self.directory / "trajectory.jsonl")
        self.counts = Counter()
        self.saved_images = 0
        self.video = None
        self.video_size = None
        self.closed = False
        self.outcome = {"status": "running"}
        delta = world.get_settings().fixed_delta_seconds
        if not delta or delta <= 0:
            raise RuntimeError("Recording requires a synchronous fixed simulation step")
        self.fps = 1.0 / delta
        (self.directory / "rgb").mkdir()
        self._write_manifest()
        try:
            self.monitor.start()
        except Exception as error:
            self.close(error)
            raise

    def step(self, policy, input_data, timestamp):
        try:
            snapshot = self.world.get_snapshot()
            observation = collect_observation(
                self.world, self.ego, int(snapshot.frame), float(timestamp),
                destination=self.destination, route_id=self.route["route_id"],
                sensors=input_data,
            )
            # Capture state and images before the returned action is applied.
            image_path, sensor_frame = self._save_camera(input_data, observation.frame)
            base_action = policy.act(observation)
            decision = self.supervisor.supervise(observation, base_action, {})
            events = self.monitor.update(observation)
            self.counts.update(event["event_type"] for event in events)
            self.logger.append(observation, base_action, decision.action, events,
                               supervisor_intervened=decision.intervened)
            self.trajectory.append(build_trajectory_record(
                observation.frame, sensor_frame, float(timestamp), image_path,
                decision.action.to_dict(), observation.ego["location"],
                observation.ego["rotation"], observation.ego["velocity"],
            ))
            self._write_manifest()
            return decision.action.to_carla()
        except Exception as error:
            self.outcome = {"status": "failed", "error": repr(error)}
            self._write_manifest()
            raise

    def _save_camera(self, input_data, world_frame):
        if "rgb_0" not in input_data:
            raise RuntimeError("Expected SimLingo front camera rgb_0 is missing")
        sensor_frame, camera = input_data["rgb_0"]
        if int(sensor_frame) != world_frame:
            raise RuntimeError("Front camera frame {} does not match world frame {}".format(
                sensor_frame, world_frame))
        if not self.images:
            return Path(""), int(sensor_frame)
        import cv2
        import numpy as np
        from PIL import Image

        bgr = np.ascontiguousarray(camera[:, :, :3])
        if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError("Expected an 8-bit BGR/BGRA camera image")
        height, width = bgr.shape[:2]
        if self.video is None:
            self.video_size = (width, height)
            self.video = cv2.VideoWriter(str(self.directory / "trajectory.mp4"),
                                        cv2.VideoWriter_fourcc(*"mp4v"), self.fps,
                                        self.video_size)
            if not self.video.isOpened():
                raise RuntimeError("Could not open trajectory.mp4 encoder")
        elif self.video_size != (width, height):
            raise ValueError("Camera resolution changed during the episode")
        relative = Path("rgb") / "frame_{:06d}.png".format(world_frame)
        Image.fromarray(bgr[:, :, ::-1]).save(str(self.directory / relative))
        self.video.write(bgr)
        self.saved_images += 1
        return relative, int(sensor_frame)

    def close(self, error=None):
        if self.closed:
            return
        self.closed = True
        if error is not None:
            self.outcome = {"status": "failed", "error": repr(error)}
        elif self.outcome["status"] == "running":
            self.outcome = {"status": "closed", "note": "Consult official results for completion and infractions."}
        try:
            self.monitor.close()
        except Exception as cleanup_error:
            self.outcome["cleanup_error"] = repr(cleanup_error)
        finally:
            if self.video is not None:
                self.video.release()
            self._write_manifest()

    def _write_manifest(self):
        payload = {
            "policy": "simlingo", "backend": "leaderboard", "seed": self.seed,
            "route": self.route, "supervisor": self.supervisor.name,
            "episode_records": self.logger.records_written,
            "trajectory_records": self.trajectory.records_written,
            "saved_images": self.saved_images, "event_counts": dict(self.counts),
            "camera": "rgb_0", "video_fps": self.fps,
            "sensor_timing": {"source": "sensor_callback_frame", "camera": "rgb_0", "strict_alignment": True},
            "fixed_delta_seconds": 1.0 / self.fps,
            "map": self.map_name,
            "route_geometry": self.route.get("geometry", []),
            "detectors": {"collision": "carla_collision_sensor", "red_light_violation": "trigger_exit_heuristic_v1"},
            "video": "trajectory.mp4" if self.saved_images else None,
            "timestamp_basis": "Leaderboard game time, seconds",
            "observation_phase": "before returned action is applied",
            "outcome": self.outcome,
            "authoritative_result": "Parent run simulation_results.json",
            "label_review": "pending; heuristic labels require audit",
        }
        temporary = self.directory / "manifest.json.tmp"
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.directory / "manifest.json")
