"""CARLA 录像工具。"""

from pathlib import Path

from .client import CarlaSession


def query_recorder_info(session: CarlaSession, rec_file: Path, show_all: bool = False) -> str:
    return session.client.show_recorder_file_info(str(rec_file), show_all)


def replay_recorder(
    session: CarlaSession,
    rec_file: Path,
    start_time: float = 0.0,
    duration: float = 0.0,
    time_factor: float = 1.0,
    follow_actor_id: int = 0,
    ignore_hero: bool = True,
) -> None:
    session.client.set_replayer_time_factor(time_factor)
    session.client.set_replayer_ignore_hero(ignore_hero)
    session.client.replay_file(str(rec_file), start_time, duration, follow_actor_id)
