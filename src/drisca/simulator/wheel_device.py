"""G29 方向盘轴与按钮输入。"""

import ctypes
from importlib.metadata import distribution

import pygame

from drisca.core.config import WheelControlConfig

SPRING_SATURATION = 40
SPRING_COEFFICIENT = 40


class G29WheelDevice:
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
            self.joystick.get_axis(config.steering_axis),
            (1.0 - self.joystick.get_axis(config.throttle_axis)) / 2.0,
            (1.0 - self.joystick.get_axis(config.brake_axis)) / 2.0,
        )

    def close(self) -> None:
        stopped = self.sdk.LogiStopSpringForce(self.config.device_index)
        self.sdk.LogiSteeringShutdown()
        self.joystick.quit()
        pygame.joystick.quit()
        if not stopped:
            raise RuntimeError('方向盘力反馈关闭失败')
