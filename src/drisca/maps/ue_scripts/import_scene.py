"""UE 内部脚本：通过 Datasmith 导入 RoadRunner 场景、语义归档并生成 OpenDRIVE 路由与出生点。"""

import json
import os
import traceback

import unreal  # ty: ignore[import-not-found]

_TAG = '[drisca-maps]'
_SEMANTICS = (
    'Road',
    'SideWalk',
    'RoadLine',
    'Ground',
    'Building',
    'Vehicles',
    'Pedestrian',
    'TrafficSign',
    'TrafficLight',
    'Vegetation',
    'Other',
    'Bridge',
    'Terrain',
    'None',
)


def _log(message: str) -> None:
    unreal.log(f'{_TAG} {message}')
    print(f'{_TAG} {message}', flush=True)


def _warn(message: str) -> None:
    unreal.log_warning(f'{_TAG} {message}')
    print(f'{_TAG} WARN {message}', flush=True)


def _fail(message: str) -> None:
    unreal.log_error(f'{_TAG} {message}')
    raise RuntimeError(message)


def _clean_previous(map_name: str) -> None:
    level_path = f'/Game/Carla/Maps/{map_name}'
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    current = world.get_map_name() if world else ''
    if map_name in current:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(
            '/Game/Carla/Maps/TestMaps/EmptyMap'
        )

    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        _log(f'清理旧关卡：{level_path}')
        unreal.EditorAssetLibrary.delete_asset(level_path)

    import_dir = f'/Game/RRImport/{map_name}'
    if unreal.EditorAssetLibrary.does_directory_exist(import_dir):
        _log(f'清理旧导入目录：{import_dir}')
        unreal.EditorAssetLibrary.delete_directory(import_dir)

    for semantic in _SEMANTICS:
        folder = f'/Game/Carla/Static/{semantic}/{map_name}'
        if unreal.EditorAssetLibrary.does_directory_exist(folder):
            unreal.EditorAssetLibrary.delete_directory(folder)


def _add_simple_collision(meshes: list[object]) -> None:
    subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if subsystem is None:
        _warn('未获取到 StaticMeshEditorSubsystem，跳过简单碰撞补充')
        return
    shape = unreal.ScriptingCollisionShapeType.BOX
    added = 0
    for mesh in meshes:
        if subsystem.get_simple_collision_count(mesh) <= 0:
            subsystem.add_simple_collisions(mesh, shape)
            unreal.EditorAssetLibrary.save_loaded_asset(mesh)
            added += 1
    _log(f'简单碰撞补充完成：{added}/{len(meshes)}')


def main() -> None:
    params: dict[str, str] = globals().get('DRISCA_MAP_PARAMS', {})
    scene = params.get('scene', '')
    map_name = params.get('map', '')
    out_dir = params.get('out', '')
    template = params.get('template', '')
    segmentation_path = params.get('segmentation', '')

    if not scene or not map_name:
        _fail('缺少必需参数 scene / map')
    if not hasattr(unreal, 'DatasmithSceneElement'):
        _fail('DatasmithImporter 未启用，请在 uproject 中启用 DatasmithContent 与 DatasmithImporter')

    _clean_previous(map_name)

    level_path = f'/Game/Carla/Maps/{map_name}'
    level_sys = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    created = (
        level_sys.new_level_from_template(level_path, template)
        if template
        else level_sys.new_level(level_path)
    )
    if not created:
        _fail(f'创建关卡失败：{level_path}')

    dest = f'/Game/RRImport/{map_name}'
    _log(f'Datasmith 导入：{scene} -> {dest}')
    element = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(scene)
    if element is None:
        _fail(f'Datasmith 无法打开文件：{scene}')
    result = element.import_scene(dest)
    meshes = list(getattr(result, 'imported_meshes', []) or [])
    actors = list(getattr(result, 'imported_actors', []) or [])
    if not meshes and not actors:
        _fail('Datasmith 导入结果为空')
    _log(f'导入完成：{len(meshes)} 个网格，{len(actors)} 个 Actor')

    segments: dict[str, str] = {}
    if segmentation_path and os.path.isfile(segmentation_path):
        with open(segmentation_path, encoding='utf-8') as fh:
            segments = json.load(fh).get('meshes', {})

    moved = 0
    unmatched: list[str] = []
    for mesh in meshes:
        name = mesh.get_name()
        semantic = segments.get(name)
        if not semantic:
            unmatched.append(name)
            continue
        source = mesh.get_path_name().split('.')[0]
        target = f'/Game/Carla/Static/{semantic}/{map_name}/{name}'
        if unreal.EditorAssetLibrary.rename_asset(source, target):
            moved += 1
        else:
            unmatched.append(name)
    _log(f'语义归档完成：移动 {moved} 个，未匹配 {len(unmatched)} 个')

    _add_simple_collision(meshes)

    actor_class = unreal.load_class(None, '/Script/Carla.OpenDriveActor')
    if actor_class is None:
        _fail('找不到 /Script/Carla.OpenDriveActor')
    actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        actor_class, unreal.Vector(0, 0, 0)
    )
    if actor is None:
        _fail('生成 AOpenDriveActor 失败')
    actor.set_editor_property('bGenerateRoutes', True)
    actor.set_editor_property('bAddSpawners', True)

    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    if not unreal.EditorLoadingAndSavingUtils.save_current_level():
        _fail(f'保存关卡失败：{level_path}')

    summary = {
        'map': map_name,
        'level': level_path,
        'import_dest': dest,
        'meshes': len(meshes),
        'actors': len(actors),
        'moved': moved,
        'unmatched': len(unmatched),
    }
    os.makedirs(out_dir or os.getcwd(), exist_ok=True)
    summary_path = os.path.join(out_dir or os.getcwd(), 'import-result.json')
    with open(summary_path, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    _log(f'导入摘要已写入：{summary_path}')


try:
    main()
except Exception:
    traceback.print_exc()
    raise
