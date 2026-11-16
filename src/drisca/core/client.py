"""显式管理 CARLA 连接与世界设置。"""

from dataclasses import dataclass

import carla

from .config import CarlaConnectionConfig, WeatherConfig, WorldConfig
from .weather import to_carla_weather


@dataclass(slots=True, frozen=True)
class PreflightResult:
    ok: bool
    server_version: str = ''
    client_version: str = ''
    current_map: str = ''
    available_maps: tuple[str, ...] = ()
    error: str = ''


class CarlaSession:
    def __init__(self, conn_cfg: CarlaConnectionConfig) -> None:
        self.conn_cfg = conn_cfg
        self.client: carla.Client

    def connect(self) -> None:
        try:
            client = carla.Client(self.conn_cfg.host, self.conn_cfg.port)
            client.set_timeout(self.conn_cfg.timeout)
            client.get_server_version()
        except RuntimeError as exc:
            raise ConnectionError(f'CARLA 连接失败：{self.conn_cfg.host}:{self.conn_cfg.port}') from exc
        self.client = client

    def preflight_check(self) -> PreflightResult:
        try:
            return PreflightResult(
                ok=True,
                server_version=self.client.get_server_version(),
                client_version=self.client.get_client_version(),
                current_map=self.map.name,
                available_maps=tuple(self.client.get_available_maps()),
            )
        except RuntimeError as exc:
            return PreflightResult(ok=False, error=str(exc))

    def prepare_world(self, world_cfg: WorldConfig) -> None:
        if world_cfg.load_map or self.map.name.rsplit('/', 1)[-1] != world_cfg.map_name.rsplit('/', 1)[-1]:
            self.client.load_world(world_cfg.map_name)
        self.apply_weather(world_cfg.weather)
        self._clear_actors()

    def set_sync_mode(self, enabled: bool, simulation_fps: int = 60) -> None:
        settings = self.world.get_settings()
        settings.synchronous_mode = enabled
        settings.fixed_delta_seconds = 1.0 / simulation_fps if enabled else 0.0
        self.world.apply_settings(settings)
        self.client.get_trafficmanager(self.conn_cfg.tm_port).set_synchronous_mode(enabled)

    def force_reset_after_experiment(self, clear_actors: bool = True) -> None:
        self.set_sync_mode(False)
        if clear_actors:
            self._clear_actors()

    def _clear_actors(self) -> None:
        actors = self.world.get_actors()
        commands = [carla.command.DestroyActor(actor) for actor in actors.filter('vehicle.*')]
        commands += [carla.command.DestroyActor(actor) for actor in actors.filter('walker.pedestrian.*')]
        responses = self.client.apply_batch_sync(commands)
        for response in responses:
            if response.error:
                raise RuntimeError(f'清理场景失败：{response.error}')

    def apply_weather(self, weather_cfg: WeatherConfig) -> None:
        self.world.set_weather(to_carla_weather(weather_cfg))

    @property
    def world(self) -> carla.World:
        return self.client.get_world()

    @property
    def map(self) -> carla.Map:
        return self.world.get_map()

    @property
    def blueprint_library(self) -> carla.BlueprintLibrary:
        return self.world.get_blueprint_library()
