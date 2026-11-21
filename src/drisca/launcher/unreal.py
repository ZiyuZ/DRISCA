"""将主机配置转换为 CARLA Unreal 启动参数。"""

from pathlib import Path
from typing import Literal

from drisca.core.config import MachineConfig
from drisca.core.paths import PROJECT_ROOT


def launch_arguments(config: MachineConfig, kind: Literal['editor', 'packaged']) -> tuple[list[str], Path]:
    runtime = config.carla_runtime

    def required_file(value: str, label: str) -> Path:
        if not value:
            raise ValueError(f'请在主机配置中填写{label}')
        path = (PROJECT_ROOT / value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'{label}不存在：{path}')
        return path

    if config.carla.host not in ('127.0.0.1', 'localhost') or config.driving_view.host not in (
        '127.0.0.1',
        'localhost',
    ):
        raise ValueError('启动本机 Unreal 时，CARLA 地址应设为 127.0.0.1 或 localhost')
    executable = required_file(
        runtime.editor_executable if kind == 'editor' else runtime.packaged_executable,
        'UE 编辑器路径' if kind == 'editor' else 'CARLA 打包程序路径',
    )
    args = [str(executable)]
    if kind == 'editor':
        args.extend([str(required_file(runtime.project, 'CARLA 工程路径')), '-game'])
    width, height = config.display.resolution
    x, y = config.display.position
    log_path = PROJECT_ROOT / '.cache' / 'logs' / 'carla-unreal.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args.extend(
        [
            '-fullscreen' if config.display.fullscreen else '-windowed',
            '-ForceRes',
            f'-ResX={width}',
            f'-ResY={height}',
            f'-WinX={x}',
            f'-WinY={y}',
            '-ini:Game:[/Script/EngineSettings.GeneralProjectSettings]:'
            f'bUseBorderlessWindow={config.display.borderless}',
            f'-carla-rpc-port={config.carla.port}',
            f'-carla-streaming-port={config.carla.port + 1}',
            f'-DriscaDrivingPort={config.driving_view.port}',
            f'-quality-level={runtime.quality}',
            f'-ExecCmds=t.MaxFPS {config.display.target_fps}',
            '-NoVSync',
            '-notrace',
            f'-abslog={log_path}',
        ]
    )
    return args, executable.parent
