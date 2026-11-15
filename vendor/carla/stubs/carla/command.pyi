# ty: ignore
# ruff: noqa

from typing import Any

import carla

class Response:
    actor_id: int
    error: str
    def has_error(self) -> bool: ...

class SpawnActor:
    transform: carla.Transform
    parent_id: int
    def __init__(self, blueprint: carla.ActorBlueprint, transform: carla.Transform, parent: Any) -> None: ...
    def then(self, command: Any) -> Any: ...

class DestroyActor:
    actor_id: int
    def __init__(self, actor: Any) -> None: ...

class ApplyVehiclePhysicsControl:
    actor_id: int
    physics_control: carla.VehiclePhysicsControl
    def __init__(self, actor: Any, physics_control: carla.VehiclePhysicsControl) -> None: ...

class ApplyVehicleControl:
    actor_id: int
    control: carla.VehicleControl
    def __init__(self, actor: Any, control: carla.VehicleControl) -> None: ...

class ApplyVehicleAckermannControl:
    actor_id: int
    control: carla.VehicleAckermannControl
    def __init__(self, actor: Any, control: carla.VehicleAckermannControl) -> None: ...

class ApplyWalkerControl:
    actor_id: int
    control: carla.WalkerControl
    def __init__(self, actor: Any, control: carla.WalkerControl) -> None: ...

class ApplyTransform:
    actor_id: int
    transform: carla.Transform
    def __init__(self, actor: Any, transform: carla.Transform) -> None: ...

class ApplyWalkerState:
    actor_id: int
    transform: carla.Transform
    speed: float
    def __init__(self, actor: Any, transform: carla.Transform, speed: float) -> None: ...

class ApplyTargetVelocity:
    actor_id: int
    velocity: carla.Vector3D
    def __init__(self, actor: Any, velocity: carla.Vector3D) -> None: ...

class ApplyTargetAngularVelocity:
    actor_id: int
    angular_velocity: carla.Vector3D
    def __init__(self, actor: Any, angular_velocity: carla.Vector3D) -> None: ...

class ApplyImpulse:
    actor_id: int
    impulse: carla.Vector3D
    def __init__(self, actor: Any, impulse: carla.Vector3D) -> None: ...

class ApplyForce:
    actor_id: int
    force: carla.Vector3D
    def __init__(self, actor: Any, force: carla.Vector3D) -> None: ...

class ApplyAngularImpulse:
    actor_id: int
    impulse: carla.Vector3D
    def __init__(self, actor: Any, impulse: carla.Vector3D) -> None: ...

class ApplyTorque:
    actor_id: int
    torque: carla.Vector3D
    def __init__(self, actor: Any, torque: carla.Vector3D) -> None: ...

class SetSimulatePhysics:
    actor_id: int
    enabled: bool
    def __init__(self, actor: Any, enabled: bool) -> None: ...

class SetAutopilot:
    actor_id: int
    enabled: bool
    tm_port: uint16
    def __init__(self, actor: Any, enabled: bool, tm_port: uint16 = ...) -> None: ...

class SetVehicleLightState:
    actor_id: int
    light_state: carla.VehicleLightState
    def __init__(self, actor: Any, light_state: carla.VehicleLightState) -> None: ...

class SetEnableGravity:
    actor_id: Any
    enabled: bool
    def __init__(self, actor: Any, enabled: bool) -> None: ...

class ShowDebugTelemetry:
    actor_id: Any
    enabled: bool
    def __init__(self, actor: Any, enabled: bool) -> None: ...
