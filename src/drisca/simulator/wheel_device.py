"""方向盘轴与按钮输入。"""

import ctypes
from importlib.metadata import distribution

import pygame

from drisca.core.config import WheelButton, WheelControlConfig

SPRING_SATURATION = 40
SPRING_COEFFICIENT = 40
WHEEL_AXES = {'steering': 0, 'throttle': 1, 'brake': 2}
WHEEL_BUTTONS: dict[WheelButton, int] = {
    WheelButton.CROSS: 0,
    WheelButton.SQUARE: 1,
    WheelButton.CIRCLE: 2,
    WheelButton.TRIANGLE: 3,
    WheelButton.RIGHT_PADDLE: 4,
    WheelButton.LEFT_PADDLE: 5,
    WheelButton.R2: 6,
    WheelButton.L2: 7,
    WheelButton.SHARE: 8,
    WheelButton.OPTIONS: 9,
    WheelButton.R3: 10,
    WheelButton.L3: 11,
    WheelButton.PLUS: 19,
    WheelButton.MINUS: 20,
    WheelButton.DIAL_RIGHT: 21,
    WheelButton.DIAL_LEFT: 22,
    WheelButton.DIAL_PRESS: 23,
    WheelButton.LOGO: 24,
}


class WheelDevice:
    def __init__(self, config: WheelControlConfig) -> None:
        self.config = config
        pygame.joystick.init()
        if config.device_index >= pygame.joystick.get_count():
            raise RuntimeError('方向盘未连接')
        self.joystick = pygame.joystick.Joystick(config.device_index)
        sdk_path = distribution('logitech-steering-wheel').locate_file(
            'logitech_steering_wheel/lib/x64/LogitechSteeringWheelEnginesWrapper.dll'
        )
        self.sdk = ctypes.WinDLL(str(sdk_path))
        self.sdk.LogiSteeringInitialize.argtypes = [ctypes.c_bool]
        self.sdk.LogiSteeringInitialize.restype = ctypes.c_bool
        self.sdk.LogiUpdate.restype = ctypes.c_bool
        self.sdk.LogiIsConnected.argtypes = [ctypes.c_int]
        self.sdk.LogiIsConnected.restype = ctypes.c_bool
        self.sdk.LogiHasForceFeedback.argtypes = [ctypes.c_int]
        self.sdk.LogiHasForceFeedback.restype = ctypes.c_bool
        self.sdk.LogiPlaySpringForce.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.sdk.LogiPlaySpringForce.restype = ctypes.c_bool
        self.sdk.LogiStopSpringForce.argtypes = [ctypes.c_int]
        self.sdk.LogiStopSpringForce.restype = ctypes.c_bool
        self.sdk.LogiSteeringShutdown.restype = None
        if not self.sdk.LogiSteeringInitialize(False):
            raise RuntimeError('方向盘 SDK 初始化失败')
        try:
            if not self.sdk.LogiUpdate() or not self.sdk.LogiIsConnected(config.device_index):
                raise RuntimeError('方向盘 SDK 未检测到设备')
            if not self.sdk.LogiHasForceFeedback(config.device_index):
                raise RuntimeError('方向盘不支持力反馈')
            if not self.sdk.LogiPlaySpringForce(
                config.device_index, 0, SPRING_SATURATION, SPRING_COEFFICIENT
            ):
                raise RuntimeError('方向盘回正力启动失败')
        except Exception:
            self.sdk.LogiSteeringShutdown()
            raise

    def read_axes(self) -> tuple[float, float, float]:
        config = self.config
        if not self.sdk.LogiUpdate() or not self.sdk.LogiIsConnected(config.device_index):
            raise RuntimeError('方向盘连接中断')
        return (
            self.joystick.get_axis(WHEEL_AXES['steering']),
            (1.0 - self.joystick.get_axis(WHEEL_AXES['throttle'])) / 2.0,
            (1.0 - self.joystick.get_axis(WHEEL_AXES['brake'])) / 2.0,
        )

    def close(self) -> None:
        stopped = self.sdk.LogiStopSpringForce(self.config.device_index)
        self.sdk.LogiSteeringShutdown()
        self.joystick.quit()
        pygame.joystick.quit()
        if not stopped:
            raise RuntimeError('方向盘力反馈关闭失败')
