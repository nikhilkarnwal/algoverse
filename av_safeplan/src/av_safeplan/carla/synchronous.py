"""Safe synchronous-mode lifecycle management for CARLA worlds."""

from typing import Any


class SynchronousWorld:
    """Apply deterministic settings and restore the original state on exit."""

    def __init__(self, world: Any, traffic_manager: Any, fixed_delta_seconds: float):
        self.world = world
        self.traffic_manager = traffic_manager
        self.fixed_delta_seconds = fixed_delta_seconds
        self._original_settings = None

    def __enter__(self) -> Any:
        self._original_settings = self.world.get_settings()
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self.fixed_delta_seconds
        self.world.apply_settings(settings)
        self.traffic_manager.set_synchronous_mode(True)
        return self.world

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.traffic_manager.set_synchronous_mode(False)
        if self._original_settings is not None:
            self.world.apply_settings(self._original_settings)
