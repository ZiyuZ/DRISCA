"""项目路径与运行目录。"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
CACHE_ROOT = PROJECT_ROOT / '.cache'
RUN_CONFIG_DIR = CACHE_ROOT / 'run'
RECORDER_ROOT = PROJECT_ROOT / 'data' / 'recordings'
MAP_ROOT = CACHE_ROOT / 'map'
CONFIG_FILE = PROJECT_ROOT / 'configs' / 'machine.toml'
CONTROL_FILE = PROJECT_ROOT / 'configs' / 'control.toml'
PRESETS_DIR = PROJECT_ROOT / 'configs' / 'presets'


def resolve_db_path(configured_path: str) -> Path:
    return (PROJECT_ROOT / configured_path).resolve()


def ensure_runtime_dirs() -> None:
    for directory in (RUN_CONFIG_DIR, RECORDER_ROOT, MAP_ROOT, PRESETS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
