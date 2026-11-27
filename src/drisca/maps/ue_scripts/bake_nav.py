"""UE 内部脚本（GUI 编辑器）：放置 NavMeshBoundsVolume、静态烘焙 Recast 导航并保存关卡。"""

import json
import os
import time
from typing import Any

import unreal  # ty: ignore[import-not-found]

if getattr(unreal, '_drisca_nav_bake_active', False):
    raise SystemExit
unreal._drisca_nav_bake_active = True

MAP_NAME = os.environ.get('DRISCA_MAP_NAME', '')
_raw_bounds = os.environ.get('DRISCA_MAP_BOUNDS', '')
BOUNDS: list[float] | None = json.loads(_raw_bounds) if _raw_bounds else None

_state: dict[str, Any] = {'started': None, 'phase': 0, 'last': 0.0, 'volume': None, 'done': False}


def _log(message: str) -> None:
    print(f'[drisca-nav-bake] {message}', flush=True)


def _recast_actors() -> list[Any]:
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    return [a for a in actors if isinstance(a, unreal.RecastNavMesh)]


def _ensure_navigation(world: object) -> object:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
    volumes = [a for a in actors if isinstance(a, unreal.NavMeshBoundsVolume)]
    navs = [a for a in actors if isinstance(a, unreal.RecastNavMesh)]

    keep = [n for n in navs if 'CarlaWalker' in n.get_actor_label()]
    if keep and len(keep) != len(navs):
        for nav in navs:
            if nav not in keep:
                subsystem.destroy_actor(nav)

    if BOUNDS and len(BOUNDS) == 6:
        center = unreal.Vector(
            (BOUNDS[0] + BOUNDS[3]) * 50.0,
            (BOUNDS[1] + BOUNDS[4]) * 50.0,
            (BOUNDS[2] + BOUNDS[5]) * 50.0,
        )
        size = unreal.Vector(
            max(BOUNDS[3] - BOUNDS[0], 10.0) * 100.0,
            max(BOUNDS[4] - BOUNDS[1], 10.0) * 100.0,
            max(BOUNDS[5] - BOUNDS[2], 200.0) * 100.0,
        )
    else:
        center = unreal.Vector(0.0, 0.0, 10000.0)
        size = unreal.Vector(100000.0, 100000.0, 40000.0)

    volume = volumes[0] if volumes else subsystem.spawn_actor_from_class(unreal.NavMeshBoundsVolume, center)
    volume.set_actor_location(center, False, False)
    volume.set_actor_scale3d(unreal.Vector(size.x / 200.0, size.y / 200.0, size.z / 200.0))

    nav_system = unreal.NavigationSystemV1.get_navigation_system(world)
    if nav_system:
        nav_system.on_navigation_bounds_updated(volume)
    return volume


def _on_tick(_delta: float) -> None:
    now = time.time()
    started = _state['started']
    if not isinstance(started, float):
        _state['started'] = now
        return

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    elapsed = now - started
    phase = _state['phase']

    if phase == 0:
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        if len(actors) < 100 or elapsed < 20.0:
            return
        _state['phase'] = 1
        _state['t1'] = now
        _log(f'准备导航范围（actors={len(actors)}）')
        _state['volume'] = _ensure_navigation(world)
        return

    if phase == 1:
        t1 = float(_state.get('t1', now))
        if now - t1 < 5.0:
            return
        navs = _recast_actors()
        if not navs:
            retry = int(_state.get('retry', 0)) + 1
            _state['retry'] = retry
            if retry <= 3:
                unreal.SystemLibrary.execute_console_command(world, 'rr.RefreshNav')
                _state['t1'] = now - 3.0
                return
        for nav in navs:
            nav.set_editor_property('runtime_generation', unreal.RuntimeGenerationType.STATIC)
        _log('执行静态导航重建（rr.RefreshNav）')
        unreal.SystemLibrary.execute_console_command(world, 'rr.RefreshNav')
        _state['phase'] = 2
        _state['t2'] = now
        return

    if phase == 2:
        t2 = float(_state.get('t2', now))
        navs = _recast_actors()
        if not _state.get('stats') and now - t2 > 20.0:
            _state['stats'] = True
            unreal.SystemLibrary.execute_console_command(world, 'rr.NavStats')
        if (now - t2 > 40.0 and navs) or now - t2 > 180.0:
            _state['phase'] = 3
        return

    if phase == 3 and not _state['done']:
        _state['done'] = True
        saved = unreal.EditorLoadingAndSavingUtils.save_map(world, f'/Game/Carla/Maps/{MAP_NAME}')
        if not saved:
            unreal.EditorLoadingAndSavingUtils.save_current_level()
        _log('导航烘焙完成并已保存关卡')
        unreal.SystemLibrary.quit_editor()


unreal.register_slate_post_tick_callback(_on_tick)
_log('导航烘焙回调已注册')
