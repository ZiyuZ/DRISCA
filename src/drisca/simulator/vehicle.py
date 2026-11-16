"""主车生成与控制。"""

from typing import cast

import carla

from drisca.core.config import EgoVehicleConfig


class EgoVehicle:
    def __init__(self, world: carla.World, config: EgoVehicleConfig, tm_port: int) -> None:
        blueprint = world.get_blueprint_library().find(config.blueprint)
        blueprint.set_attribute('role_name', config.role_name)
        point = config.spawn_point
        transform = carla.Transform(
            carla.Location(x=point.x, y=point.y, z=point.z),
            carla.Rotation(pitch=point.pitch, yaw=point.yaw, roll=point.roll),
        )
        self.actor = cast(carla.Vehicle, world.spawn_actor(blueprint, transform))
        self.tm_port = tm_port
        self.autopilot = False
        self.set_autopilot(config.init_autopilot)

    def set_autopilot(self, enabled: bool) -> None:
        self.actor.set_autopilot(enabled, self.tm_port)
        self.autopilot = enabled

    def apply_control(self, control: carla.VehicleControl) -> None:
        if not self.autopilot:
            self.actor.apply_control(control)

    def close(self) -> None:
        self.actor.destroy()
