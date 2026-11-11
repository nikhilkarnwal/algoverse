"""Custom ScenarioRunner encounters. CARLA imports are isolated from offline tools.

One scenario owns a sequential encounter group. Actors are placed before driving,
never teleported into the ego. Route-level collision termination is installed by
the opt-in evaluator entry point. No ego controls or official sources are changed.
"""

import json
import math
import os
from pathlib import Path

import carla
import py_trees
from srunner.scenarios.basic_scenario import BasicScenario
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.timer import GameTime

from av_safeplan.scenarios.custom_catalog import load_catalog

STOP_REQUEST = None


class CustomEncounterStop(py_trees.behaviour.Behaviour):
    """End the route normally when a custom encounter is censored, not crashed."""
    def __init__(self):
        super().__init__("CustomEncounterCensored")

    def update(self):
        return py_trees.common.Status.SUCCESS if STOP_REQUEST is not None else py_trees.common.Status.RUNNING


class AVSafePlanRepeatedEncounters(BasicScenario):
    def __init__(self, world, ego_vehicles, config, timeout=300):
        self.catalog = load_catalog(os.environ["AV_SAFEPLAN_CUSTOM_CATALOG"])
        self.case_name = config.other_parameters["case"]["value"]
        self.case = self.catalog["cases"][self.case_name]
        self.timeout = timeout
        self.encounters = []
        self.log = None
        self.ego = ego_vehicles[0]
        self.origin = config.trigger_points[0]
        self.forward = self.origin.get_forward_vector()
        self.right = self.origin.get_right_vector()
        output = Path(os.environ["AV_SAFEPLAN_SIMLINGO_OUTPUT"]) / "custom_encounters"
        output.mkdir(parents=True, exist_ok=True)
        # Unique file per scenario invocation; never append a rerun to old evidence.
        from uuid import uuid4
        self.log = (output / (self.case_name + "-" + uuid4().hex + ".jsonl")).open("x")
        try:
            super().__init__(config.name, ego_vehicles, config, world,
                             terminate_on_failure=True, criteria_enable=False)
        except Exception:
            self.remove_all_actors()
            self.log.close()
            raise

    def point(self, distance, lateral=0.0, height=0.3):
        return carla.Location(x=self.origin.location.x + distance*self.forward.x + lateral*self.right.x,
                              y=self.origin.location.y + distance*self.forward.y + lateral*self.right.y,
                              z=self.origin.location.z + height)

    def progress(self, location):
        delta = location - self.origin.location
        return delta.x*self.forward.x + delta.y*self.forward.y

    def emit(self, event, encounter=None, **details):
        snapshot = self.world.get_snapshot()
        self.log.write(json.dumps(dict(event=event, encounter_id=encounter,
            frame=snapshot.frame, timestamp_seconds=snapshot.timestamp.elapsed_seconds,
            case=self.case_name, family=self.case["family"], split="train",
            review="deferred", loss_mask=False, **details)) + "\n")
        self.log.flush()

    def _initialize_actors(self, config):
        world_map = self.world.get_map()
        end = self.catalog["first_encounter_m"] + (self.catalog["encounters_per_route"]-1)*self.catalog["spacing_m"] + 45
        # Fail closed on turns, junctions, grades, lane changes, or insufficient length.
        lane_key = None
        for distance in range(0, int(end)+1, 2):
            point = self.point(distance, height=0)
            wp = world_map.get_waypoint(point, project_to_road=False, lane_type=carla.LaneType.Driving)
            if wp is None or wp.is_junction or abs(wp.transform.location.z-point.z) > 0.5:
                raise ValueError("Custom route requires a flat, junction-free driving corridor")
            key = (wp.road_id, wp.section_id, wp.lane_id)
            lane_key = key if lane_key is None else lane_key
            direction = wp.transform.get_forward_vector()
            if key != lane_key or direction.x*self.forward.x + direction.y*self.forward.y < 0.995:
                raise ValueError("Custom route must remain straight and on one lane")
            if self.case["family"] == "static_obstacle":
                left = wp.get_left_lane()
                if (left is None or left.lane_type != carla.LaneType.Driving or
                        left.lane_id*wp.lane_id <= 0 or left.is_junction):
                    raise ValueError("Passing lane must continue throughout the encounter corridor")
        if self.ego.get_location().distance(self.origin.location) > 8:
            raise ValueError("Custom scenario must initialize at the route start")
        for index in range(self.catalog["encounters_per_route"]):
            distance = self.catalog["first_encounter_m"] + index*self.catalog["spacing_m"]
            wp = world_map.get_waypoint(self.point(distance, height=0))
            lateral, model = 0.0, "vehicle.lincoln.mkz_2017"
            family = self.case["family"]
            # Crossing spans the ego lane, beginning off its right edge.
            if family == "pedestrian":
                lateral, model = wp.lane_width/2 + 1.0, "walker.pedestrian.0001"
                side = world_map.get_waypoint(self.point(distance, lateral, 0), project_to_road=False,
                                             lane_type=carla.LaneType.Sidewalk)
                if side is None:
                    raise ValueError("Pedestrian spawn requires a real right-side sidewalk")
                destination = world_map.get_waypoint(self.point(distance, -lateral, 0), project_to_road=False,
                                                    lane_type=carla.LaneType.Sidewalk)
                if destination is None:
                    raise ValueError("Pedestrian crossing must end on a real sidewalk, not another traffic lane")
            if family == "static_obstacle":
                left = wp.get_left_lane()
                if left is None or left.lane_type != carla.LaneType.Driving or left.lane_id*wp.lane_id <= 0:
                    raise ValueError("Obstacle requires an adjacent same-direction left passing lane")
                # Clearance checked using actual bounding boxes after spawn.
                lateral = -wp.lane_width/2 - left.lane_width + self.case["passing_space_m"] + 1.0
            transform = carla.Transform(self.point(distance, lateral), self.origin.rotation)
            actor = CarlaDataProvider.request_new_actor(model, transform, rolename="custom_hazard")
            if actor is None:
                raise RuntimeError("Hazard spawn failed; refusing a silently missing encounter")
            self.other_actors.append(actor)
            radius = math.hypot(actor.bounding_box.extent.x, actor.bounding_box.extent.y)
            for other in self.world.get_actors():
                if other.id == actor.id or not (other.type_id.startswith("vehicle.") or other.type_id.startswith("walker.")):
                    continue
                other_radius = math.hypot(other.bounding_box.extent.x, other.bounding_box.extent.y)
                if actor.get_location().distance(other.get_location()) < radius + other_radius + 0.5:
                    raise ValueError("Hazard lacks safe spawn clearance")
            if family == "static_obstacle":
                clearance = lateral - actor.bounding_box.extent.y + wp.lane_width/2 + left.lane_width
                if clearance < 2*self.ego.bounding_box.extent.y + 0.5 or abs(clearance-self.case["passing_space_m"]) > 0.25:
                    raise ValueError("Actual obstacle width does not meet requested passing clearance")
                if lateral + actor.bounding_box.extent.y > wp.lane_width/2 - 0.1:
                    raise ValueError("Obstacle extends outside the drivable corridor")
            if family != "pedestrian":
                actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
            item = dict(id="{}-{:02d}".format(config.name, index+1), actor=actor,
                        distance=distance, crossing_width=wp.lane_width+2.0, state="waiting")
            self.encounters.append(item)
            self.emit("prepared", item["id"], actor_id=actor.id, distance_m=distance,
                      parameters=self.case, actor_type=actor.type_id)

    def _setup_scenario_trigger(self, config):
        return None  # Own stabilization and ego-distance triggers; not wall-clock timers.

    def _create_behavior(self):
        return EncounterSequence(self)

    def _create_test_criteria(self):
        return []  # Evaluator owns collision and route criteria.

    def remove_all_actors(self):
        super().remove_all_actors()
        if self.log is not None and not self.log.closed:
            for item in self.encounters:
                if item["state"] != "cleared":
                    self.emit("not_completed", item["id"], state=item["state"])
            self.log.close()


class EncounterSequence(py_trees.behaviour.Behaviour):
    def __init__(self, scenario):
        super().__init__("AVSafePlanSequentialEncounters")
        self.scenario, self.index, self.started = scenario, 0, None

    def update(self):
        global STOP_REQUEST
        s = self.scenario
        now = GameTime.get_time()
        if self.started is None:
            self.started = now
        if now-self.started < s.catalog["stabilization_seconds"]:
            return py_trees.common.Status.RUNNING
        if self.index == len(s.encounters):
            return py_trees.common.Status.SUCCESS
        item = s.encounters[self.index]
        actor = item["actor"]
        if not actor.is_alive:
            raise RuntimeError("Custom encounter actor disappeared")
        progress = s.progress(s.ego.get_location())
        distance = item["distance"]-progress
        family = s.case["family"]
        if item["state"] == "waiting":
            if distance < 0:
                raise RuntimeError("Ego passed an unactivated custom encounter")
            if distance > 35:
                return py_trees.common.Status.RUNNING
            item.update(state="active", started=now, triggered=False)
            s.emit("activated", item["id"])
        if now-item["started"] > s.catalog["encounter_timeout_seconds"]:
            s.emit("timeout", item["id"])
            item["state"] = "censored"
            STOP_REQUEST = "encounter_timeout"
            return py_trees.common.Status.RUNNING
        if family == "lead_brake":
            if s.progress(actor.get_location()) > item["distance"] + 40:
                s.emit("not_reached", item["id"], reason="lead exceeded encounter envelope")
                item["state"] = "censored"
                STOP_REQUEST = "lead_envelope_exhausted"
                return py_trees.common.Status.RUNNING
            gap = s.progress(actor.get_location())-progress-actor.bounding_box.extent.x-s.ego.bounding_box.extent.x
            speed = actor.get_velocity().length()
            ego_speed = s.ego.get_velocity().length()
            road_map = s.world.get_map()
            ego_wp = road_map.get_waypoint(s.ego.get_location())
            lead_wp = road_map.get_waypoint(actor.get_location())
            following = (ego_wp.road_id, ego_wp.section_id, ego_wp.lane_id) == (lead_wp.road_id, lead_wp.section_id, lead_wp.lane_id)
            ego_forward = s.ego.get_transform().get_forward_vector()
            following = following and ego_forward.x*s.forward.x + ego_forward.y*s.forward.y > 0.98
            if not item["triggered"] and following and ego_speed >= 1.0 and speed >= 0.5 and 2.0 <= gap <= s.case["trigger_gap_m"]:
                item["triggered"] = True
                s.emit("braking", item["id"], measured_gap_m=gap, ego_speed_mps=ego_speed,
                       lead_speed_mps=speed, brake_command=s.case["brake"])
            # Let ego establish the following gap. Never accelerate away at a
            # fixed target while ego slows; no teleporting or ego override.
            target = min(s.case["lead_speed_mps"], max(0.0, ego_speed-0.6))
            if now-item.get("last_motion_log", -1e9) >= 0.5:
                s.emit("following_state", item["id"], measured_gap_m=gap,
                       ego_speed_mps=ego_speed, lead_speed_mps=speed,
                       target_lead_speed_mps=target, same_lane=following, braking=item["triggered"])
                item["last_motion_log"] = now
            actor.apply_control(carla.VehicleControl(
                throttle=0.0 if item["triggered"] else min(0.5, max(0.0, (target-speed)*0.3)),
                brake=s.case["brake"] if item["triggered"] else min(0.35, max(0.0, (speed-target)*0.3))))
            cleared = progress > s.progress(actor.get_location()) + 12
        elif family == "pedestrian":
            if not item["triggered"] and distance <= s.case["trigger_distance_m"]:
                item.update(triggered=True, crossing_start=now)
                s.emit("crossing", item["id"], measured_distance_m=distance)
            if item["triggered"]:
                crossing = (now-item["crossing_start"])*s.case["crossing_speed_mps"] < item["crossing_width"]
                actor.apply_control(carla.WalkerControl(direction=carla.Vector3D(-s.right.x, -s.right.y, 0),
                    speed=s.case["crossing_speed_mps"] if crossing else 0.0))
            cleared = progress > item["distance"] + 12
        else:
            cleared = progress > item["distance"] + 12
        if cleared:
            item["state"] = "cleared"
            s.emit("cleared", item["id"])
            CarlaDataProvider.remove_actor_by_id(actor.id)
            self.index += 1
        return py_trees.common.Status.RUNNING
