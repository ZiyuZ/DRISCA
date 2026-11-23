"""CARLA 录像工具。"""

from pathlib import Path

from .client import NativeApiClient


def query_recorder_info(client: NativeApiClient, rec_file: Path, show_all: bool = False) -> str:
    return str(client.recorder_info(str(rec_file), show_all)['info'])


def replay_recorder(
    client: NativeApiClient,
    rec_file: Path,
    start_time: float = 0.0,
    duration: float = 0.0,
    time_factor: float = 1.0,
    follow_actor_id: int = 0,
    ignore_hero: bool = True,
) -> None:
    client.recorder_replay(
        str(rec_file),
        start_time=start_time,
        duration=duration,
        follow_actor_id=follow_actor_id,
        time_factor=time_factor,
        ignore_hero=ignore_hero,
    )
