"""Select a small, reproducible Town12 subset from public route definitions."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import xml.etree.ElementTree as ElementTree

import yaml


@dataclass(frozen=True)
class UpstreamSource:
    repository: str
    revision: str
    directory: str


@dataclass(frozen=True)
class ScenarioFamily:
    name: str
    selection: str
    scenario_types: Tuple[str, ...]
    required_criteria: Tuple[str, ...]
    expected_outcome: str
    requires_live_validation: bool
    implementation_type: Optional[str]
    parameters: Mapping[str, str]


@dataclass(frozen=True)
class UpstreamScenarioConfig:
    town: str
    sources: Mapping[str, UpstreamSource]
    families: Tuple[ScenarioFamily, ...]


@dataclass(frozen=True)
class RouteCandidate:
    source_file: str
    route_id: str
    town: str
    scenario_index: Optional[int]
    scenario_name: Optional[str]
    scenario_type: Optional[str]
    trigger_x: Optional[float]
    trigger_y: Optional[float]
    trigger_z: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilySelection:
    family: ScenarioFamily
    candidate: RouteCandidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family.name,
            "selection": self.family.selection,
            "required_criteria": list(self.family.required_criteria),
            "expected_outcome": self.family.expected_outcome,
            "requires_live_validation": self.family.requires_live_validation,
            "candidate": self.candidate.to_dict(),
        }


def load_upstream_config(path: Path) -> UpstreamScenarioConfig:
    """Load and validate the public-scenario source and family definitions."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("upstream scenario config must be a mapping")
    if int(payload.get("version", 0)) != 1:
        raise ValueError("unsupported upstream scenario config version")

    town = str(payload.get("town", "")).strip()
    if not town:
        raise ValueError("upstream scenario config requires a town")

    sources_payload = payload.get("sources")
    if not isinstance(sources_payload, Mapping) or not sources_payload:
        raise ValueError("upstream scenario config requires sources")
    sources: Dict[str, UpstreamSource] = {}
    for name, source in sources_payload.items():
        if not isinstance(source, Mapping):
            raise ValueError("source {!r} must be a mapping".format(name))
        sources[str(name)] = UpstreamSource(
            repository=_required_text(source, "repository", "source {!r}".format(name)),
            revision=_required_text(source, "revision", "source {!r}".format(name)),
            directory=_required_text(source, "directory", "source {!r}".format(name)),
        )

    families_payload = payload.get("families")
    if not isinstance(families_payload, Mapping) or not families_payload:
        raise ValueError("upstream scenario config requires families")
    families: List[ScenarioFamily] = []
    for name, family in families_payload.items():
        if not isinstance(family, Mapping):
            raise ValueError("family {!r} must be a mapping".format(name))
        selection = str(family.get("selection", "scenario")).strip()
        if selection not in {"scenario", "route"}:
            raise ValueError("family {!r} has invalid selection".format(name))
        scenario_types = tuple(str(value) for value in family.get("scenario_types", []))
        if selection == "scenario" and not scenario_types:
            raise ValueError("scenario family {!r} requires scenario_types".format(name))
        criteria = tuple(str(value) for value in family.get("required_criteria", []))
        if not criteria:
            raise ValueError("family {!r} requires at least one criterion".format(name))
        families.append(ScenarioFamily(
            name=str(name),
            selection=selection,
            scenario_types=scenario_types,
            required_criteria=criteria,
            expected_outcome=_required_text(
                family,
                "expected_outcome",
                "family {!r}".format(name),
            ),
            requires_live_validation=bool(family.get("requires_live_validation", True)),
            implementation_type=str(family["implementation_type"]) if family.get("implementation_type") else None,
            parameters={str(key): str(value) for key, value in family.get("parameters", {}).items()},
        ))
    return UpstreamScenarioConfig(town=town, sources=sources, families=tuple(families))


def find_route_files(paths: Iterable[Path]) -> List[Path]:
    """Expand XML files and directories into one deterministic file list."""
    route_files = set()
    for path in paths:
        expanded = path.expanduser().resolve()
        if expanded.is_file() and expanded.suffix.lower() == ".xml":
            route_files.add(expanded)
        elif expanded.is_dir():
            route_files.update(expanded.rglob("*.xml"))
    return sorted(route_files, key=lambda value: str(value))


def discover_candidates(route_files: Sequence[Path], town: str) -> List[RouteCandidate]:
    """Read Leaderboard/ScenarioRunner XML without importing either project."""
    candidates: List[RouteCandidate] = []
    for source_file in route_files:
        try:
            root = ElementTree.parse(str(source_file)).getroot()
        except ElementTree.ParseError:
            continue
        for route in root.findall(".//route"):
            route_town = str(route.attrib.get("town", ""))
            if route_town != town:
                continue
            route_id = str(route.attrib.get("id", ""))
            candidates.append(RouteCandidate(
                source_file=str(source_file),
                route_id=route_id,
                town=route_town,
                scenario_index=None,
                scenario_name=None,
                scenario_type=None,
                trigger_x=None,
                trigger_y=None,
                trigger_z=None,
            ))
            for index, scenario in enumerate(route.findall(".//scenario")):
                trigger = scenario.find("trigger_point")
                candidates.append(RouteCandidate(
                    source_file=str(source_file),
                    route_id=route_id,
                    town=route_town,
                    scenario_index=index,
                    scenario_name=scenario.attrib.get("name"),
                    scenario_type=scenario.attrib.get("type"),
                    trigger_x=_optional_float(trigger, "x"),
                    trigger_y=_optional_float(trigger, "y"),
                    trigger_z=_optional_float(trigger, "z"),
                ))
    return sorted(candidates, key=_candidate_sort_key)


def select_week1_candidates(
    config: UpstreamScenarioConfig,
    candidates: Sequence[RouteCandidate],
) -> Tuple[List[FamilySelection], List[str]]:
    """Choose one stable public candidate per reduced Week 1 scenario family."""
    selections: List[FamilySelection] = []
    missing: List[str] = []
    for family in config.families:
        if family.selection == "route":
            if family.scenario_types:
                matching = [
                    candidate
                    for candidate in candidates
                    if candidate.scenario_type in family.scenario_types
                ]
            else:
                matching = [
                    candidate for candidate in candidates if candidate.scenario_index is None
                ]
        else:
            matching = [
                candidate
                for candidate in candidates
                if candidate.scenario_type in family.scenario_types
            ]
        if not matching:
            missing.append(family.name)
            continue
        selections.append(FamilySelection(family=family, candidate=matching[0]))
    return selections, missing


def write_reduced_routes(selections: Sequence[FamilySelection], output_path: Path) -> None:
    """Write one minimal route per family, stripping unrelated scenario instances."""
    output_root = ElementTree.Element("routes")
    for output_id, selection in enumerate(selections):
        candidate = selection.candidate
        source_root = ElementTree.parse(candidate.source_file).getroot()
        source_route = _find_route(source_root, candidate.route_id, candidate.town)
        if source_route is None:
            raise ValueError(
                "route {!r} disappeared from {}".format(candidate.route_id, candidate.source_file)
            )
        route = deepcopy(source_route)
        route.set("id", str(output_id))
        scenarios = route.find("scenarios")
        if scenarios is not None:
            scenario_nodes = list(scenarios.findall("scenario"))
            for index, scenario in enumerate(scenario_nodes):
                keep = (
                    selection.family.selection == "scenario"
                    and index == candidate.scenario_index
                )
                if not keep:
                    scenarios.remove(scenario)
                else:
                    if selection.family.implementation_type:
                        scenario.set("type", selection.family.implementation_type)
                    for name, value in selection.family.parameters.items():
                        parameter = scenario.find(name)
                        if parameter is None:
                            parameter = ElementTree.SubElement(scenario, name)
                        parameter.set("value", value)
        _crop_route_around_trigger(route, candidate)
        output_root.append(route)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree.ElementTree(output_root)
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)


def _find_route(root: Any, route_id: str, town: str) -> Optional[Any]:
    for route in root.findall(".//route"):
        if route.attrib.get("id") == route_id and route.attrib.get("town") == town:
            return route
    return None


def _crop_route_around_trigger(
    route: Any,
    candidate: RouteCandidate,
    waypoints_before: int = 1,
    waypoints_after: int = 1,
) -> None:
    """Keep a bounded route window around the selected scenario anchor."""
    if candidate.trigger_x is None or candidate.trigger_y is None:
        return
    waypoints = route.find("waypoints")
    if waypoints is None:
        return
    positions = list(waypoints.findall("position"))
    if len(positions) < 3:
        return

    def squared_distance(position: Any) -> float:
        x = float(position.attrib["x"])
        y = float(position.attrib["y"])
        z = float(position.attrib.get("z", candidate.trigger_z or 0.0))
        return (
            (x - candidate.trigger_x) ** 2
            + (y - candidate.trigger_y) ** 2
            + (z - (candidate.trigger_z or z)) ** 2
        )

    anchor = min(range(len(positions)), key=lambda index: squared_distance(positions[index]))
    start = max(0, anchor - waypoints_before)
    end = min(len(positions), anchor + waypoints_after + 1)
    if end - start < 2:
        return
    retained = set(positions[start:end])
    for position in positions:
        if position not in retained:
            waypoints.remove(position)


def _candidate_sort_key(candidate: RouteCandidate) -> Tuple[str, Tuple[int, Any], int, str]:
    route_id: Tuple[int, Any]
    try:
        route_id = (0, int(candidate.route_id))
    except ValueError:
        route_id = (1, candidate.route_id)
    scenario_index = -1 if candidate.scenario_index is None else candidate.scenario_index
    return (candidate.source_file, route_id, scenario_index, candidate.scenario_type or "")


def _required_text(value: Mapping[str, Any], key: str, context: str) -> str:
    result = str(value.get(key, "")).strip()
    if not result:
        raise ValueError("{} requires {}".format(context, key))
    return result


def _optional_float(element: Optional[Any], key: str) -> Optional[float]:
    if element is None or key not in element.attrib:
        return None
    return float(element.attrib[key])
