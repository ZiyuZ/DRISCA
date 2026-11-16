"""键盘与方向盘输入。"""

from dataclasses import dataclass
from typing import Literal

import carla
import pygame
from loguru import logger

from drisca.core.config import ControlConfig
from drisca.simulator.wheel_device import G29WheelDevice


@dataclass(slots=True, frozen=True)
class InputAction:
    name: str
    source: Literal['keyboard', 'wheel']


class InputController:
    def __init__(self, config: ControlConfig) -> None:
        self.config = config
        self.steer = 0.0
        self.wheel = None
        if config.wheel.enable_wheel:
            self.wheel = G29WheelDevice(config.wheel)
        self.keys = {name: tuple(pygame.key.key_code(key) for key in keys) for name, keys in config.keyboard}

    def read(self, delta: float) -> tuple[carla.VehicleControl, list[InputAction]]:
        actions: list[InputAction] = []
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                actions.append(InputAction('quit', 'keyboard'))
            elif event.type == pygame.KEYDOWN:
                actions.extend(
                    InputAction(name, 'keyboard') for name, keys in self.keys.items() if event.key in keys
                )
            elif (
                event.type == pygame.JOYBUTTONDOWN
                and self.wheel is not None
                and event.instance_id == self.wheel.joystick.get_instance_id()
            ):
                if self.config.wheel.show_button_key:
                    logger.info('方向盘按钮编号：{}', event.button)
                actions.extend(
                    InputAction(name, 'wheel')
                    for name, buttons in self.config.wheel
                    if isinstance(buttons, tuple) and event.button in buttons
                )
        pressed = pygame.key.get_pressed()

        def active(name: str) -> bool:
            return any(pressed[key] for key in self.keys[name])

        if self.wheel is not None:
            steer, throttle, brake = self.wheel.read_axes()
        else:
            target = float(active('drive_right')) - float(active('drive_left'))
            change = 2.0 * delta
            self.steer = max(self.steer - change, min(self.steer + change, target))
            steer = self.steer
            throttle = float(active('drive_forward'))
            brake = float(active('drive_backward'))
        return carla.VehicleControl(throttle=throttle, steer=steer, brake=brake), actions

    def close(self) -> None:
        if self.wheel is not None:
            self.wheel.close()
