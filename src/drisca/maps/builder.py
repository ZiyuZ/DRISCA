"""开发机环境解析、自检（doctor）与 RoadRunner Datasmith 导入调度。"""

import json
import os
import shutil
import tomllib
from pathlib import Path

from drisca.core.paths import CACHE_ROOT, PROJECT_ROOT
from drisca.maps.datasmith import extract_datasmith, locate_scene
from drisca.maps.models import CheckItem, DatasmithExtract, MapEnvironment, MapToolError
from drisca.maps.pack import BASE_RELEASE_NAME, run_logged_command

DEFAULT_LEVEL_TEMPLATE = '/Game/Carla/Maps/BaseMap/BaseMap'
_UE_SCRIPTS_DIR = Path(__file__).resolve().parent / 'ue_scripts'


def _derive_engine_root(editor_exe: Path | None) -> Path | None:
    if editor_exe is None:
        return None
    # <EngineRoot>/Engine/Binaries/Win64/UnrealEditor.exe
    parents = editor_exe.resolve().parents
    if len(parents) >= 4 and parents[2].name.lower() == 'engine':
        return parents[3]
    return None


def _derive_carla_root(project: Path | None) -> Path | None:
    if project is None:
        return None
    # <CarlaRoot>/Unreal/CarlaUnreal/CarlaUnreal.uproject
    parents = project.resolve().parents
    if len(parents) >= 3 and parents[1].name.lower() == 'unreal':
        return parents[2]
    return None


def _read_machine_runtime() -> dict[str, str]:
    machine_toml = PROJECT_ROOT / 'configs' / 'machine.toml'
    if not machine_toml.is_file():
        return {}
    data = tomllib.loads(machine_toml.read_text(encoding='utf-8'))
    runtime = data.get('carla_runtime')
    return runtime if isinstance(runtime, dict) else {}


def resolve_environment(
    *,
    carla_root: Path | None = None,
    project: Path | None = None,
    engine_root: Path | None = None,
    server_dir: Path | None = None,
    base_release: Path | None = None,
) -> MapEnvironment:
    """结合命令行参数与 configs/machine.toml 解析 CARLA/UE 路径。"""
    runtime = _read_machine_runtime()

    editor_raw = runtime.get('editor_executable', '')
    project_raw = runtime.get('project', '')
    packaged_raw = runtime.get('packaged_executable', '')

    resolved_project = project or (Path(project_raw) if project_raw else None)
    resolved_carla = carla_root or _derive_carla_root(resolved_project)
    if resolved_project is None and resolved_carla is not None:
        resolved_project = resolved_carla / 'Unreal' / 'CarlaUnreal' / 'CarlaUnreal.uproject'

    editor_from_cfg = Path(editor_raw) if editor_raw else None
    resolved_engine = engine_root or _derive_engine_root(editor_from_cfg)

    editor_exe = (
        resolved_engine / 'Engine' / 'Binaries' / 'Win64' / 'UnrealEditor.exe'
        if resolved_engine is not None
        else editor_from_cfg
    )
    editor_cmd = editor_exe.parent / 'UnrealEditor-Cmd.exe' if editor_exe is not None else None

    resolved_packaged = server_dir
    if resolved_packaged is None and packaged_raw:
        pkg_exe = Path(packaged_raw)
        if pkg_exe.is_file():
            resolved_packaged = pkg_exe.parent
        elif pkg_exe.is_dir():
            resolved_packaged = pkg_exe

    resolved_base = base_release
    if resolved_base is None and resolved_carla is not None:
        candidate = resolved_carla / 'Build' / 'Package' / f'{BASE_RELEASE_NAME}-release-metadata.tar.gz'
        if candidate.is_file():
            resolved_base = candidate

    return MapEnvironment(
        carla_root=resolved_carla,
        project=resolved_project,
        engine_root=resolved_engine,
        editor_executable=editor_exe,
        editor_cmd_executable=editor_cmd,
        packaged_dir=resolved_packaged,
        base_release=resolved_base,
    )


def doctor(env: MapEnvironment) -> list[CheckItem]:
    """检查本机 UE、CARLA 源码、必需插件与基础包元数据是否齐全。"""
    items: list[CheckItem] = []

    items.append(
        CheckItem(
            name='UnrealEditor-Cmd.exe',
            ok=env.editor_cmd_executable is not None and env.editor_cmd_executable.is_file(),
            detail=str(env.editor_cmd_executable or '未配置（请检查 configs/machine.toml 或 --engine-root）'),
        )
    )
    items.append(
        CheckItem(
            name='UnrealEditor.exe',
            ok=env.editor_executable is not None and env.editor_executable.is_file(),
            detail=str(env.editor_executable or '未配置'),
        )
    )
    items.append(
        CheckItem(
            name='CarlaUnreal.uproject',
            ok=env.project is not None and env.project.is_file(),
            detail=str(env.project or '未配置'),
        )
    )

    required_plugins = ('DatasmithContent', 'DatasmithImporter', 'PythonScriptPlugin')
    if env.project is not None and env.project.is_file():
        uproject = json.loads(env.project.read_text(encoding='utf-8'))
        enabled = {
            str(p.get('Name'))
            for p in uproject.get('Plugins', [])
            if isinstance(p, dict) and p.get('Enabled')
        }
        missing = [name for name in required_plugins if name not in enabled]
        items.append(
            CheckItem(
                name='uproject 必需插件',
                ok=not missing,
                detail='全部已启用' if not missing else f'缺少：{", ".join(missing)}',
            )
        )
        rr_mat = env.project.parent / 'Plugins' / 'RoadRunnerMaterials' / 'RoadRunnerMaterials.uplugin'
        items.append(
            CheckItem(
                name='RoadRunnerMaterials 插件',
                ok=rr_mat.is_file(),
                detail=str(rr_mat) if rr_mat.is_file() else '缺失（如导入 RoadRunner 材质需放置该插件）',
            )
        )

    runuat = env.engine_root / 'Engine' / 'Build' / 'BatchFiles' / 'RunUAT.bat' if env.engine_root else None
    items.append(
        CheckItem(
            name='RunUAT.bat',
            ok=runuat is not None and runuat.is_file(),
            detail=str(runuat or '未找到'),
        )
    )
    items.append(
        CheckItem(
            name='基础包 release-metadata',
            ok=env.base_release is not None and env.base_release.exists(),
            detail=str(env.base_release or '未找到（需先构建 Shipping 基础包）'),
        )
    )
    return items


def _ue_script(name: str) -> Path:
    path = _UE_SCRIPTS_DIR / name
    if not path.is_file():
        raise MapToolError(f'缺少内置 UE 脚本：{path}')
    return path


def import_map(
    env: MapEnvironment,
    scene_input: Path,
    map_name: str,
    *,
    template: str | None = DEFAULT_LEVEL_TEMPLATE,
    bake_nav: bool = True,
    timeout: float = 1800.0,
    dry_run: bool = False,
) -> DatasmithExtract:
    """将 RoadRunner .udatasmith/.zip 导入 CARLA 源码工程，并可选烘焙静态导航。"""
    if env.editor_cmd_executable is None or not env.editor_cmd_executable.is_file():
        raise MapToolError(
            '找不到 UnrealEditor-Cmd.exe', hint='请通过 --engine-root 或 configs/machine.toml 配置'
        )
    if env.project is None or not env.project.is_file():
        raise MapToolError(
            '找不到 CarlaUnreal.uproject', hint='请通过 --project 或 configs/machine.toml 配置'
        )
    if env.content_dir is None:
        raise MapToolError('无法推导 Content/Carla 目录')

    work_dir = CACHE_ROOT / 'maps' / map_name
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_path = locate_scene(scene_input, work_dir, full=not dry_run)
    extract = extract_datasmith(scene_path, work_dir, map_name)

    params = {
        'scene': str(extract.scene_path),
        'map': map_name,
        'out': str(work_dir),
        'content': str(env.content_dir),
        'template': template or '',
        'segmentation': str(extract.segmentation_path),
    }

    bootstrap = work_dir / 'bootstrap_import_scene.py'
    import_cmd = [
        str(env.editor_cmd_executable),
        str(env.project),
        '-run=pythonscript',
        f'-script={bootstrap}',
        '-unattended',
        '-nosplash',
        '-nopause',
        '-stdout',
        '-FullStdOutLogOutput',
    ]

    if dry_run:
        print('将执行导入命令：')
        print('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in import_cmd))
        return extract

    # 写出 OpenDRIVE 到 CARLA 工程目录（需在导入触发 AOpenDriveActor 之前就位）
    if extract.xodr_path is not None:
        xodr_dst = env.content_dir / 'Maps' / 'OpenDrive' / f'{map_name}.xodr'
        xodr_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extract.xodr_path, xodr_dst)

    script_src = _ue_script('import_scene.py').read_text(encoding='utf-8')
    bootstrap.write_text(f'DRISCA_MAP_PARAMS = {params!r}\n{script_src}', encoding='utf-8')

    _, _, tail = run_logged_command(
        import_cmd,
        work_dir / 'import.log',
        timeout=timeout,
    )
    summary_path = work_dir / 'import-result.json'
    if not summary_path.is_file():
        detail = '\n'.join(tail[-25:])
        raise MapToolError(
            f'UE 导入未生成结果摘要（{summary_path}）：\n{detail}',
            hint=f'完整日志：{work_dir / "import.log"}',
        )

    if bake_nav:
        if env.editor_executable is None or not env.editor_executable.is_file():
            raise MapToolError('烘焙导航需要 UnrealEditor.exe，当前未找到该可执行文件')
        nav_bootstrap = work_dir / 'bootstrap_bake_nav.py'
        nav_bootstrap.write_text(_ue_script('bake_nav.py').read_text(encoding='utf-8'), encoding='utf-8')
        gui_cmd = [
            str(env.editor_executable),
            str(env.project),
            f'/Game/Carla/Maps/{map_name}',
            f'-ExecCmds=py {nav_bootstrap}',
            '-windowed',
            '-ResX=800',
            '-ResY=600',
            '-nosplash',
            '-nosound',
        ]
        nav_env = os.environ.copy()
        nav_env['DRISCA_MAP_NAME'] = map_name
        if extract.bounds_m is not None:
            nav_env['DRISCA_MAP_BOUNDS'] = json.dumps(list(extract.bounds_m))
        for pass_idx in (1, 2):
            run_logged_command(
                gui_cmd,
                work_dir / f'bake-nav-pass{pass_idx}.log',
                timeout=timeout,
                env=nav_env,
            )

    return extract
