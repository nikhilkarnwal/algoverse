"""ScenarioRunner extension isolating signal compliance from actor-flow risk."""

import py_trees

from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (
    ScenarioTimeout,
    TrafficLightFreezer,
)
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import (
    DriveDistance,
    WaitEndIntersection,
)
from srunner.tools.background_manager import ChangeOppositeBehavior, HandleJunctionScenario
from srunner.tools.scenario_helper import get_same_dir_lanes
from signalized_junction_left_turn import SignalizedJunctionLeftTurn, get_value_parameter


class AVSafePlanSignalizedJunctionLeftTurn(SignalizedJunctionLeftTurn):
    """Use the public junction lights without its conflicting vehicle flow."""

    def _create_behavior(self):
        delay = get_value_parameter(self.config, "green_light_delay", float, 20.0)
        if not 0.0 < delay <= 60.0:
            raise ValueError("green_light_delay must be within (0, 60] seconds")
        self._green_light_delay = delay

        sequence = py_trees.composites.Sequence(name="AVSafePlanSignalizedJunctionLeftTurn")
        if self.route_mode:
            sequence.add_child(HandleJunctionScenario(
                clear_junction=True,
                clear_ego_entry=True,
                remove_entries=get_same_dir_lanes(self._source_wp),
                remove_exits=get_same_dir_lanes(self._sink_wp),
                stop_entries=True,
                extend_road_exit=self._sink_dist + 20,
            ))
            sequence.add_child(ChangeOppositeBehavior(active=False))

        active = py_trees.composites.Parallel(
            policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE
        )
        end_condition = py_trees.composites.Sequence(name="EndIntersection")
        end_condition.add_child(WaitEndIntersection(self.ego_vehicles[0]))
        end_condition.add_child(DriveDistance(self.ego_vehicles[0], self._end_distance))
        active.add_child(end_condition)
        active.add_child(ScenarioTimeout(self._scenario_timeout, self.config.name))

        lights = py_trees.composites.Sequence(name="Traffic Light Behavior")
        lights.add_child(TrafficLightFreezer(self._init_tl_dict, duration=delay))
        lights.add_child(TrafficLightFreezer(self._flow_tl_dict))
        active.add_child(lights)
        sequence.add_child(active)

        if self.route_mode:
            sequence.add_child(ChangeOppositeBehavior(active=True))
        return sequence
