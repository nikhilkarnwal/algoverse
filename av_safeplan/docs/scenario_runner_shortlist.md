# Existing ScenarioRunner scenario shortlist

Source inspection: installed v0.9.15, commit
`d12d8bb788201ebf6f03e55b9c5169f9dcb2ea87`.
Availability means source/configuration is present, not that a live run passed.
Town12 counts are scenario entries across installed Leaderboard route XMLs,
not unique physical locations or independent examples.

| Requested scenario | Actual encounter in pinned implementation | Town12 entries under exact name | Packaged example towns |
|---|---|---:|---|
| VehicleTurningRight | Turning ego meets crossing bicycle (`vehicle.diamondback.century`) | 0 | Town01–Town04 |
| VehicleTurningLeft | Turning ego meets crossing bicycle | 0 | Town01–Town04 |
| StationaryObjectCrossing | Static container (`static.prop.container`); cyclist docstring is stale | 0 | Town02–Town05 |
| DynamicObjectCrossing | Pedestrian (`walker.*`) emerges behind an occluder | 358 | Town02–Town05 |
| NoSignalJunctionCrossing | Vehicle crossing conflict at an unsignalized junction | 0 | Town03 |
| SignalizedJunctionRightTurn | Signalized right turn / traffic interaction | 120 | Town03–Town05 |
| SignalizedJunctionLeftTurn | Signalized left turn / traffic interaction | 124 | Town03–Town05 |

All seven are included as candidates. Start Town12 work with existing official
`DynamicObjectCrossing` and signalized-turn route entries. Keep exact standalone
turning, stationary-object and unsignalized examples as secondary validation
options: their packaged towns are outside the current Town12 scope and require
an explicit execution plan, map availability and adapter compatibility checks.
Do not assume changing a town attribute makes an example valid on Town12.

`VehicleTurningRoute` is an existing route-aware bicycle variant (119 Town12
entries), not an identical alias for either standalone turning scenario.
`VehicleTurningRoutePedestrian` is a separate pedestrian variant (86 entries).
Bicycle events need an explicit category/subtype rule before evaluation; do not
count them as pedestrian positives.

Other retained upstream candidates: `HardBreakRoute` (587),
`OppositeVehicleRunningRedLight` (161), `StaticCutIn` (117),
`PedestrianCrossing` (95), `ParkingCrossingPedestrian` (126),
`ConstructionObstacle` (128), and `ConstructionObstacleTwoWays` (136).
Construction scenarios provide Town12 static-prop coverage without porting
`StationaryObjectCrossing`. `ParkedObstacle` remains vehicle-category.

## Constraints

- Use existing upstream behavior implementations and official configurations;
  do not invent custom encounter behavior. Route selection/windowing, policy
  adapters and recording are plumbing, and must preserve scenario semantics.
- The local `AVSafePlanSignalizedJunctionLeftTurn` wrapper is not upstream and
  is excluded from the proposed new upstream-only collection default. Historical
  runs remain intact and retain their original provenance.
- Signalized turns do not guarantee ego red-light positives. Confirm actual
  controlling-signal state and crossing evidence using the route criteria.
  `OppositeVehicleRunningRedLight` concerns the other vehicle's violation.
- Before collecting, verify scenario loading (no skips), actor identity and
  presence, geometry, full policy route support, and recording/evidence alignment.
- No new maps, custom scenarios, installations or simulator runs were performed
  for this shortlist. Existing launch configurations have not been switched yet.
