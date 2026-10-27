"""Compatibility entry point for the pinned upstream inference agent."""

import os
from pathlib import Path
import sys
from uuid import uuid4

from av_safeplan.policies.simlingo import SimLingoPolicy
from av_safeplan.telemetry.leaderboard import LeaderboardEpisodeRecorder

# Upstream imports scenario_logger as a sibling rather than a package module.
sys.path.insert(0, str(Path(os.environ["SIMLINGO_ROOT"]) / "team_code"))
from team_code.agent_simlingo import LingoAgent


def get_entry_point():
    return "SafePlanLingoAgent"


class SafePlanLingoAgent(LingoAgent):
    def setup(self, path_to_conf_file, route_index=None):
        self._episode_recorder = None
        self._shared_policy = None
        self._recording_enabled = os.environ.get("AV_SAFEPLAN_SIMLINGO_RECORD", "1") == "1"
        super().setup(path_to_conf_file, route_index=route_index)
        self._shared_policy = SimLingoPolicy.from_initialized_agent(self, super().run_step)

    def _ensure_recorder(self):
        if self._episode_recorder is not None:
            return
        from srunner.scenariomanager.carla_data_provider import CarlaDataProvider

        world = CarlaDataProvider.get_world()
        heroes = [actor for actor in world.get_actors().filter("vehicle.*")
                  if actor.attributes.get("role_name") == "hero"]
        if len(heroes) != 1 or not self._global_plan_world_coord:
            raise RuntimeError("Recording requires one hero vehicle and a global route plan")
        start = self._global_plan_world_coord[0][0].location
        destination = self._global_plan_world_coord[-1][0].location
        route = {
            "route_id": "{}:{:.3f},{:.3f}->{:.3f},{:.3f}".format(
                world.get_map().name, start.x, start.y, destination.x, destination.y),
            "source_xml": os.environ.get("ROUTES"),
            "selected_route_ids": os.environ.get("AV_SAFEPLAN_SIMLINGO_ROUTE_SUBSET", ""),
            "geometry": [{"x": float(transform.location.x), "y": float(transform.location.y),
                          "z": float(transform.location.z)} for transform, _ in self._global_plan_world_coord],
        }
        output = Path(os.environ["AV_SAFEPLAN_SIMLINGO_OUTPUT"]) / "telemetry" / ("episode-" + uuid4().hex)
        self._episode_recorder = LeaderboardEpisodeRecorder(
            output, world, heroes[0], destination, route,
            int(os.environ.get("AV_SAFEPLAN_SIMLINGO_SEED", "0")),
            images=os.environ.get("AV_SAFEPLAN_SIMLINGO_IMAGES", "1") == "1",
        )

    def run_step(self, input_data, timestamp, sensors=None):
        # Retain measured sensor values for the upstream metric writer. This
        # wrapper leaves prediction and vehicle-control computation upstream.
        self._metric_timestamp = float(timestamp)
        self._metric_speed = float(input_data["speed"][1]["speed"])
        self._metric_gnss = [float(value) for value in input_data["gps"][1]]
        if not self._recording_enabled:
            return super().run_step(input_data, timestamp, sensors=sensors)
        self._ensure_recorder()
        return self._episode_recorder.step(self._shared_policy, input_data, timestamp)

    def get_metric_info(self):
        """Measured telemetry, not inferred hazard labels or safety scores."""
        return {
            "schema_version": 1,
            "step": int(self.step),
            "timestamp_seconds": self._metric_timestamp,
            "speed_mps": self._metric_speed,
            "gnss": self._metric_gnss,
        }

    def destroy(self):
        """Release model resources even after a partially completed setup.

        The published checkpoint has no data_module.encoder key, which the
        upstream destroy method assumes exists. Release only owned attributes.
        """
        recorder = getattr(self, "_episode_recorder", None)
        if recorder is not None:
            recorder.close()
        policy = getattr(self, "_shared_policy", None)
        if policy is not None:
            policy.close()
        for name in ("model", "config", "processor"):
            if hasattr(self, name):
                delattr(self, name)
