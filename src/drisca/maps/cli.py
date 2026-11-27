"""DRISCA 地图导入、烘焙与内容包管理命令行入口。"""

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from drisca.maps.builder import DEFAULT_LEVEL_TEMPLATE, doctor, import_map, resolve_environment
from drisca.maps.datasmith import extract_datasmith, locate_scene
from drisca.maps.models import MapToolError
from drisca.maps.pack import install_pack, list_packs, pack_map, remove_pack


def _add_env_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--carla-root', type=Path, default=None, help='CARLA UE5 源码根目录')
    parser.add_argument('--project', type=Path, default=None, help='CarlaUnreal.uproject 路径')
    parser.add_argument('--engine-root', type=Path, default=None, help='Unreal Engine 根目录')
    parser.add_argument('--server', type=Path, default=None, help='Shipping 基础包目录')
    parser.add_argument('--base', type=Path, default=None, help='基础包 release-metadata.tar.gz 路径')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m drisca.maps',
        description='DRISCA 自定义地图导入、独立烘焙与内容包安装工具',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_doctor = sub.add_parser('doctor', help='检查本机 UE、CARLA、插件与基础包元数据环境')
    _add_env_args(p_doctor)

    p_probe = sub.add_parser('probe', help='预检 RoadRunner 导出的 .udatasmith/.zip 文件')
    p_probe.add_argument('scene', type=Path, help='.udatasmith 或 .zip 文件路径')
    p_probe.add_argument('--map', dest='map_name', default=None, help='目标地图名（默认取文件名）')

    p_import = sub.add_parser('import', help='将 .udatasmith/.zip 导入 CARLA 源码工程')
    p_import.add_argument('scene', type=Path, help='.udatasmith 或 .zip 文件路径')
    p_import.add_argument('--map', dest='map_name', required=True, help='目标地图名')
    p_import.add_argument('--template', default=DEFAULT_LEVEL_TEMPLATE, help='关卡模板路径')
    p_import.add_argument('--no-template', action='store_true', help='创建空关卡而非使用模板')
    p_import.add_argument('--skip-nav', action='store_true', help='跳过 GUI 静态导航烘焙')
    p_import.add_argument('--timeout', type=float, default=1800.0, help='单步超时时间（秒）')
    p_import.add_argument('--dry-run', action='store_true', help='仅预检并打印执行命令')
    _add_env_args(p_import)

    p_pack = sub.add_parser('pack', help='将工程中的地图烘焙为独立 .tar.gz 内容包')
    p_pack.add_argument('--map', dest='map_name', required=True, help='地图名或 /Game/Carla/Maps/<名>')
    p_pack.add_argument('--pack-name', default=None, help='内容包名（默认与地图名一致）')
    p_pack.add_argument('--out', type=Path, default=None, help='地图包输出目录')
    p_pack.add_argument('--dry-run', action='store_true', help='仅打印烘焙命令')
    _add_env_args(p_pack)

    p_install = sub.add_parser('install', help='校验并安装独立地图包到 Shipping 基础包')
    p_install.add_argument('pack', type=Path, help='地图包 .tar.gz 路径')
    p_install.add_argument('--force', action='store_true', help='强制覆盖已安装的同名包')
    _add_env_args(p_install)

    p_list = sub.add_parser('list', help='列出 Shipping 基础包中已安装的地图包')
    _add_env_args(p_list)

    p_remove = sub.add_parser('remove', help='卸载 Shipping 基础包中的指定地图包')
    p_remove.add_argument('pack_name', help='要卸载的地图包目录名')
    _add_env_args(p_remove)

    return parser


def _require_server(args: argparse.Namespace) -> Path:
    env = resolve_environment(
        carla_root=args.carla_root,
        project=args.project,
        engine_root=args.engine_root,
        server_dir=args.server,
        base_release=args.base,
    )
    if env.packaged_dir is None:
        raise MapToolError(
            '未指定 Shipping 服务器目录',
            hint='请通过 --server 指定，或在 configs/machine.toml 配置 packaged_executable',
        )
    return env.packaged_dir


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            env = resolve_environment(
                carla_root=args.carla_root,
                project=args.project,
                engine_root=args.engine_root,
                server_dir=args.server,
                base_release=args.base,
            )
            items = doctor(env)
            all_ok = True
            for item in items:
                mark = 'OK' if item.ok else 'MISSING'
                print(f'[{mark:7}] {item.name}: {item.detail}')
                if not item.ok:
                    all_ok = False
            return 0 if all_ok else 1

        if args.command == 'probe':
            map_name = args.map_name or args.scene.stem
            with tempfile.TemporaryDirectory(prefix='drisca-maps-probe-') as tmp:
                tmp_path = Path(tmp)
                scene = locate_scene(args.scene, tmp_path, full=False)
                extract = extract_datasmith(scene, tmp_path, map_name)
                print(f'场景文件   : {extract.scene_path}')
                print(f'OpenDRIVE  : {extract.xodr_bytes} 字节（斑马线规范 {extract.crosswalk_count} 处）')
                print(f'语义网格数 : {extract.mesh_count}')
                print(f'估算范围   : {extract.bounds_m}')
                for warning in extract.warnings:
                    print(f'警告       : {warning}')
            return 0

        if args.command == 'import':
            env = resolve_environment(
                carla_root=args.carla_root,
                project=args.project,
                engine_root=args.engine_root,
                server_dir=args.server,
                base_release=args.base,
            )
            extract = import_map(
                env,
                args.scene,
                args.map_name,
                template=None if args.no_template else args.template,
                bake_nav=not args.skip_nav,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            print(
                f'完成导入：{extract.map_name}（网格语义 {extract.mesh_count}，'
                f'OpenDRIVE {extract.xodr_bytes} 字节）'
            )
            return 0

        if args.command == 'pack':
            env = resolve_environment(
                carla_root=args.carla_root,
                project=args.project,
                engine_root=args.engine_root,
                server_dir=args.server,
                base_release=args.base,
            )
            output = pack_map(
                env,
                args.map_name,
                pack_name=args.pack_name,
                out_dir=args.out,
                base_release=args.base,
                dry_run=args.dry_run,
            )
            print(f'地图包输出：{output}')
            return 0

        if args.command == 'install':
            server = _require_server(args)
            info = install_pack(args.pack, server, force=args.force)
            maps_text = ', '.join(info.maps) if info.maps else '无'
            print(f'已安装地图包：{info.name}（版本 {info.version or "-"}，地图：{maps_text}）')
            return 0

        if args.command == 'list':
            server = _require_server(args)
            packs = list_packs(server)
            if not packs:
                print(f'未安装扩展地图包：{server}')
                return 0
            for item in packs:
                maps_text = ', '.join(item.maps) if item.maps else '无'
                print(f'- {item.name} (v{item.version or "-"}): {maps_text}')
            return 0

        if args.command == 'remove':
            server = _require_server(args)
            removed = remove_pack(server, args.pack_name)
            print(f'已卸载地图包：{removed}')
            return 0

    except MapToolError as exc:
        print(f'错误：{exc.message}', file=sys.stderr)
        if exc.hint:
            print(f'提示：{exc.hint}', file=sys.stderr)
        return 1
    return 0
