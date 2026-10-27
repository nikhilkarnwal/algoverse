#!/usr/bin/env python3
"""Trim prepared Town12 routes around their selected scenario on CARLA roads."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import carla
from agents.navigation.global_route_planner import GlobalRoutePlanner


def _location(element):
    return carla.Location(
        x=float(element.attrib["x"]),
        y=float(element.attrib["y"]),
        z=float(element.attrib["z"]),
    )


def _dense_route(planner, positions):
    route = []
    for start, end in zip(positions, positions[1:]):
        for waypoint, _ in planner.trace_route(_location(start), _location(end)):
            location = waypoint.transform.location
            if not route or route[-1].distance(location) > 0.2:
                route.append(location)
    if len(route) < 3:
        raise ValueError("CARLA could not trace the prepared route")
    return route


def _window_indices(locations, trigger, before_m, after_m):
    distances = [0.0]
    for previous, current in zip(locations, locations[1:]):
        distances.append(distances[-1] + previous.distance(current))
    anchor = min(range(len(locations)), key=lambda index: locations[index].distance(trigger))
    trigger_error = locations[anchor].distance(trigger)
    if trigger_error > 5.0:
        raise ValueError("scenario trigger is {:.1f} m from its CARLA route".format(trigger_error))
    start = min(range(anchor + 1), key=lambda index: abs(distances[index] - (distances[anchor] - before_m)))
    end = min(range(anchor, len(locations)), key=lambda index: abs(distances[index] - (distances[anchor] + after_m)))
    if not start < anchor < end:
        raise ValueError("route does not extend far enough on both sides of the trigger")
    return distances, start, anchor, end, trigger_error


def _sample_indices(distances, start, anchor, end, spacing_m):
    indices = [start]
    for index in range(start + 1, end):
        if index == anchor or distances[index] - distances[indices[-1]] >= spacing_m:
            indices.append(index)
    if indices[-1] != end:
        indices.append(end)
    return indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-routes", type=Path, required=True)
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--output-routes", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--before-m", type=float, default=50.0)
    parser.add_argument("--after-m", type=float, default=80.0)
    parser.add_argument("--spacing-m", type=float, default=5.0)
    arguments = parser.parse_args()

    selection = json.loads(arguments.selection_report.read_text(encoding="utf-8"))
    client = carla.Client(arguments.host, arguments.port)
    client.set_timeout(300.0)
    world = client.get_world()
    if world.get_map().name.split("/")[-1] != selection["town"]:
        world = client.load_world(selection["town"])
    planner = GlobalRoutePlanner(world.get_map(), 1.0)

    source = ET.parse(str(arguments.input_routes)).getroot()
    output = ET.Element("routes")
    windows = []
    for item in selection["selections"]:
        route_id = item["prepared_route_id"]
        route = next((value for value in source.findall("route") if value.attrib["id"] == route_id), None)
        if route is None:
            raise ValueError("prepared route {} is missing".format(route_id))
        candidate = item["candidate"]
        trigger = carla.Location(
            x=float(candidate["trigger_x"]),
            y=float(candidate["trigger_y"]),
            z=float(candidate["trigger_z"]),
        )
        positions = list(route.find("waypoints").findall("position"))
        locations = _dense_route(planner, positions)
        distances, start, anchor, end, trigger_error = _window_indices(
            locations, trigger, arguments.before_m, arguments.after_m
        )
        sampled = _sample_indices(distances, start, anchor, end, arguments.spacing_m)
        shortened = deepcopy(route)
        waypoints = shortened.find("waypoints")
        for position in list(waypoints):
            waypoints.remove(position)
        for index in sampled:
            location = locations[index]
            ET.SubElement(waypoints, "position", {
                "x": "{:.3f}".format(location.x),
                "y": "{:.3f}".format(location.y),
                "z": "{:.3f}".format(location.z),
            })
        output.append(shortened)
        windows.append({
            "family": item["family"],
            "route_id": route_id,
            "original_length_m": round(distances[-1], 2),
            "window_length_m": round(distances[end] - distances[start], 2),
            "trigger_offset_m": round(distances[anchor] - distances[start], 2),
            "trigger_error_m": round(trigger_error, 2),
            "waypoints": len(sampled),
        })

    arguments.output_routes.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(output).write(str(arguments.output_routes), encoding="utf-8", xml_declaration=True)
    arguments.output_report.write_text(json.dumps(windows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(windows, indent=2))


if __name__ == "__main__":
    main()
