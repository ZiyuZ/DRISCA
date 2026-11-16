"""键盘与方向盘输入。"""

from dataclasses import dataclass
from typing import Literal

import carla
import pygame
from loguru import logger

from drisca.core.config import ControlConfig, KeyboardKey, WheelButton
from drisca.simulator.wheel_device import WHEEL_BUTTONS, WheelDevice

KEYBOARD_KEYS: dict[KeyboardKey, int] = {
    KeyboardKey.ESCAPE: pygame.K_ESCAPE,
    KeyboardKey.P: pygame.K_p,
    KeyboardKey.BACKSLASH: pygame.K_BACKSLASH,
    KeyboardKey.Q: pygame.K_q,
    KeyboardKey.M: pygame.K_m,
    KeyboardKey.PERIOD: pygame.K_PERIOD,
    KeyboardKey.COMMA: pygame.K_COMMA,
    KeyboardKey.SPACE: pygame.K_SPACE,
    KeyboardKey.SEMICOLON: pygame.K_SEMICOLON,
    KeyboardKey.K: pygame.K_k,
    KeyboardKey.L: pygame.K_l,
    KeyboardKey.Z: pygame.K_z,
    KeyboardKey.X: pygame.K_x,
    KeyboardKey.I: pygame.K_i,
    KeyboardKey.UP: pygame.K_UP,
    KeyboardKey.DOWN: pygame.K_DOWN,
    KeyboardKey.LEFT: pygame.K_LEFT,
    KeyboardKey.RIGHT: pygame.K_RIGHT,
    KeyboardKey.W: pygame.K_w,
    KeyboardKey.S: pygame.K_s,
    KeyboardKey.A: pygame.K_a,
    KeyboardKey.D: pygame.K_d,
    KeyboardKey.KEYPAD_1: pygame.K_KP1,
    KeyboardKey.KEYPAD_2: pygame.K_KP2,
}


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
            self.wheel = WheelDevice(config.wheel)
        self.keys = {name: KEYBOARD_KEYS[key] for name, key in config.keyboard if key != KeyboardKey.UNBOUND}
        self.buttons = {
            name: WHEEL_BUTTONS[button]
            for name, button in config.wheel
            if isinstance(button, WheelButton) and button != WheelButton.UNBOUND
        }

    def read(self, delta: float) -> tuple[carla.VehicleControl, list[InputAction]]:
        actions: list[InputAction] = []
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                actions.append(InputAction('quit', 'keyboard'))
            elif event.type == pygame.KEYDOWN:
                actions.extend(
                    InputAction(name, 'keyboard') for name, key in self.keys.items() if event.key == key
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
                    for name, button in self.buttons.items()
                    if event.button == button
                )
        pressed = pygame.key.get_pressed()

        def active(name: str) -> bool:
            key = self.keys.get(name)
            return key is not None and bool(pressed[key])

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
