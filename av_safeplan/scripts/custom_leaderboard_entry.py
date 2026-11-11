#!/usr/bin/env python3
"""Process-local registration and collision stop for custom-only route files."""

import os
from pathlib import Path
import runpy
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from av_safeplan.scenarios.custom_catalog import load_catalog


def main():
    catalog = load_catalog(os.environ["AV_SAFEPLAN_CUSTOM_CATALOG"])
    routes = ET.parse(os.environ["ROUTES"]).getroot().findall("route")
    if len(routes) != 1:
        raise ValueError("Custom collection requires one route per fresh evaluator process")
    scenarios = routes[0].findall("scenarios/scenario")
    if len(scenarios) != 1 or scenarios[0].get("type") != "AVSafePlanRepeatedEncounters":
        raise ValueError("Refusing mixed official/custom routes")
    case = scenarios[0].find("case")
    if case is None or case.get("value") not in catalog["cases"]:
        raise ValueError("Route must reference a configured custom case")

    from leaderboard.scenarios.route_scenario import RouteScenario
    from srunner.scenariomanager.scenarioatomics.atomic_criteria import CollisionTest
    from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
    from av_safeplan.scenarios.custom_runtime import AVSafePlanRepeatedEncounters, CustomEncounterStop

    original_classes = RouteScenario.get_all_scenario_classes
    original_criteria = RouteScenario._create_test_criteria
    original_build = RouteScenario.build_scenarios

    def classes(self):
        registry = original_classes(self)
        registry["AVSafePlanRepeatedEncounters"] = AVSafePlanRepeatedEncounters
        return registry

    def criteria(self):
        tree = original_criteria(self)
        collisions = [node for node in tree.children if isinstance(node, CollisionTest)]
        if len(collisions) != 1 or not hasattr(collisions[0], "_terminate_on_failure"):
            raise RuntimeError("Unsupported pinned collision criterion API")
        collisions[0]._terminate_on_failure = True
        tree.add_child(CustomEncounterStop())
        return tree

    def build(self, ego_vehicle, debug=False):
        # Upstream catches construction errors and silently skips scenarios.
        # A custom route must fail instead of recording an empty/safe-looking run.
        location = CarlaDataProvider.get_location(ego_vehicle)
        pending = list(self.missing_scenario_configurations)
        expected = [c for c in pending if location is not None and
                    c.trigger_points[0].location.distance(location) < self.INIT_THRESHOLD]
        result = original_build(self, ego_vehicle, debug=debug)
        actual = {id(s.config) for s in self.list_scenarios}
        if any(id(c) not in actual for c in expected):
            raise RuntimeError("Custom encounter construction failed; refusing silently skipped hazards")
        return result

    RouteScenario.get_all_scenario_classes = classes
    RouteScenario._create_test_criteria = criteria
    RouteScenario.build_scenarios = build
    evaluator = Path(os.environ["LEADERBOARD_ROOT"]) / "leaderboard/leaderboard_evaluator.py"
    sys.argv[0] = str(evaluator)
    runpy.run_path(str(evaluator), run_name="__main__")


if __name__ == "__main__":
    main()
