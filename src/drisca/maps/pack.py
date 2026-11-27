"""独立地图内容包（.tar.gz）的自包含校验、安装、卸载与 UAT 烘焙调度。"""

import hashlib
import json
import shutil
import subprocess
import tarfile
import time
from collections import deque
from pathlib import Path
from typing import IO

from drisca.core.paths import CACHE_ROOT
from drisca.core.types import JsonObject
from drisca.maps.models import MapEnvironment, MapToolError, PackInfo

BASE_RELEASE_NAME = 'carla-1.0-Win64'
MANIFEST_NAME = 'carla-pack.json'


def _sha256_bytes(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1 << 20):
        digest.update(chunk)
    return f'sha256:{digest.hexdigest()}'


def _sha256_file(path: Path) -> str:
    with path.open('rb') as fh:
        return _sha256_bytes(fh)


def run_logged_command(
    cmd: list[str],
    log_path: Path,
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    echo: bool = True,
) -> tuple[int, float, list[str]]:
    """执行外部命令并实时落盘日志，返回 (退出码, 耗时秒, 末尾日志行)。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tail: deque[str] = deque(maxlen=40)
    started = time.monotonic()

    with log_path.open('w', encoding='utf-8', errors='replace') as fh:
        fh.write(' '.join(cmd) + '\n\n')
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                tail.append(line.rstrip('\r\n'))
                if echo:
                    print(line, end='')
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise MapToolError(
                f'命令执行超时（{timeout:.0f} 秒）：{Path(cmd[0]).name}',
                hint=f'请查看日志：{log_path}',
            ) from None

    return int(proc.returncode or 0), time.monotonic() - started, list(tail)


def _normalize_tar_relpath(raw: str) -> str:
    cleaned = raw.replace('\\', '/').lstrip('./')
    if not cleaned or cleaned.startswith('/') or '..' in cleaned.split('/'):
        raise MapToolError(f'归档包含非法路径：{raw}')
    return cleaned


def _extract_tar_safe(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with tarfile.open(archive, 'r:*') as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()):
                continue
            rel = _normalize_tar_relpath(member.name)
            target = (dest / rel).resolve()
            if dest_resolved != target and dest_resolved not in target.parents:
                raise MapToolError(f'归档路径越界：{member.name}')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = tar.extractfile(member)
            if stream is None:
                continue
            with stream, target.open('wb') as out:
                shutil.copyfileobj(stream, out)


def read_pack_manifest(pack_file: Path) -> PackInfo:
    """从 .tar.gz 地图包中读取 carla-pack.json 清单摘要。"""
    if not pack_file.is_file():
        raise MapToolError(f'找不到地图包文件：{pack_file}')
    try:
        with tarfile.open(pack_file, 'r:*') as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                if member.name.replace('\\', '/').endswith(MANIFEST_NAME):
                    stream = tar.extractfile(member)
                    if stream is None:
                        continue
                    data = json.loads(stream.read().decode('utf-8'))
                    maps = tuple(
                        str(item['name'])
                        for item in data.get('maps', [])
                        if isinstance(item, dict) and item.get('name')
                    )
                    return PackInfo(
                        name=str(data.get('name') or pack_file.stem),
                        version=str(data.get('version') or ''),
                        maps=maps,
                        path=pack_file.resolve(),
                    )
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise MapToolError(f'无法解析地图包清单：{exc}') from exc
    raise MapToolError(f'地图包中缺少 {MANIFEST_NAME}：{pack_file}')


def list_packs(server_dir: Path) -> list[PackInfo]:
    """列出 Shipping 基础包中已安装的全部扩展地图包。"""
    if not server_dir.is_dir():
        raise MapToolError(f'Shipping 服务器目录不存在：{server_dir}')
    packs_dir = server_dir / 'CarlaUnreal' / 'Packs'
    if not packs_dir.is_dir():
        return []

    items: list[PackInfo] = []
    for entry in sorted(packs_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / MANIFEST_NAME
        maps: tuple[str, ...] = ()
        version = ''
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            maps = tuple(
                str(m['name']) for m in data.get('maps', []) if isinstance(m, dict) and m.get('name')
            )
            version = str(data.get('version') or '')
        items.append(PackInfo(name=entry.name, version=version, maps=maps, path=entry))
    return items


def verify_pack(pack_file: Path) -> PackInfo:
    """校验地图包清单与全部文件 SHA256 完整性，返回清单摘要。"""
    if not pack_file.is_file():
        raise MapToolError(f'找不到地图包文件：{pack_file}')
    try:
        with tarfile.open(pack_file, 'r:*') as tar:
            members_by_rel: dict[str, tarfile.TarInfo] = {}
            manifest_member: tarfile.TarInfo | None = None
            manifest_prefix = ''
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                rel = _normalize_tar_relpath(member.name)
                members_by_rel[rel] = member
                if rel == MANIFEST_NAME or rel.endswith(f'/{MANIFEST_NAME}'):
                    manifest_member = member
                    manifest_prefix = rel[: -len(MANIFEST_NAME)]

            if manifest_member is None:
                raise MapToolError(f'地图包中缺少 {MANIFEST_NAME}：{pack_file}')

            manifest_stream = tar.extractfile(manifest_member)
            assert manifest_stream is not None
            data = json.loads(manifest_stream.read().decode('utf-8'))
            expected_files = data.get('files')
            if not isinstance(expected_files, dict) or not expected_files:
                raise MapToolError(f'{MANIFEST_NAME} 缺少 files 校验表')

            for rel_path, expected_hash in expected_files.items():
                key = f'{manifest_prefix}{rel_path}'
                member = members_by_rel.get(key)
                if member is None:
                    raise MapToolError(f'地图包缺少清单声明的文件：{rel_path}')
                stream = tar.extractfile(member)
                assert stream is not None
                actual_hash = _sha256_bytes(stream)
                if actual_hash != expected_hash:
                    raise MapToolError(
                        f'文件校验失败：{rel_path}（期望 {expected_hash}，实际 {actual_hash}）'
                    )

            maps = tuple(
                str(item['name'])
                for item in data.get('maps', [])
                if isinstance(item, dict) and item.get('name')
            )
            return PackInfo(
                name=str(data.get('name') or pack_file.stem),
                version=str(data.get('version') or ''),
                maps=maps,
                path=pack_file.resolve(),
            )
    except MapToolError:
        raise
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise MapToolError(f'地图包校验失败：{exc}') from exc


def install_pack(pack_file: Path, server_dir: Path, *, force: bool = False) -> PackInfo:
    """校验并将独立地图包直接安装到 Shipping 基础包的 CarlaUnreal/Packs/ 目录。"""
    if not server_dir.is_dir():
        raise MapToolError(f'Shipping 服务器目录不存在：{server_dir}')
    info = verify_pack(pack_file)
    packs_dir = server_dir / 'CarlaUnreal' / 'Packs'
    target_dir = packs_dir / info.name
    if target_dir.exists():
        if not force:
            shutil.rmtree(target_dir)
        else:
            shutil.rmtree(target_dir)

    tmp_dir = CACHE_ROOT / 'maps' / f'install-staging-{info.name}'
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    try:
        _extract_tar_safe(pack_file, tmp_dir)
        extracted_root = tmp_dir / info.name
        if not (extracted_root / MANIFEST_NAME).is_file():
            extracted_root = tmp_dir
        packs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(extracted_root, target_dir)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
    return info


def remove_pack(server_dir: Path, pack_name: str) -> Path:
    """从 Shipping 基础包中卸载指定地图包目录。"""
    if not server_dir.is_dir():
        raise MapToolError(f'Shipping 服务器目录不存在：{server_dir}')
    target = server_dir / 'CarlaUnreal' / 'Packs' / pack_name
    if not target.is_dir():
        raise MapToolError(f'未找到已安装的地图包：{target}')
    shutil.rmtree(target)
    return target


def resolve_base_release(env: MapEnvironment, explicit_base: Path | None = None) -> Path:
    """定位用于地图 DLC 烘焙的基础包 release-metadata。"""
    if explicit_base is not None:
        if not explicit_base.exists():
            raise MapToolError(f'指定的 base release 不存在：{explicit_base}')
        return explicit_base
    if env.base_release is not None and env.base_release.exists():
        return env.base_release
    if env.carla_root is not None:
        tarball = env.carla_root / 'Build' / 'Package' / f'{BASE_RELEASE_NAME}-release-metadata.tar.gz'
        if tarball.is_file():
            return tarball
    if env.project is not None:
        release_dir = env.project.parent / 'Releases' / BASE_RELEASE_NAME
        if release_dir.is_dir():
            return release_dir
    raise MapToolError(
        '找不到基础包 release-metadata',
        hint='请通过 --base 指定 CARLA_1.0_release-metadata.tar.gz',
    )


def _uplugin_descriptor(name: str, *, explicitly_loaded: bool) -> JsonObject:
    return {
        'FileVersion': 3,
        'Version': 1,
        'VersionName': '1.0',
        'FriendlyName': name,
        'Description': f'DRISCA map content pack: {name}',
        'Category': 'CARLA Content Packs',
        'CanContainContent': True,
        'IsBetaVersion': False,
        'Installed': False,
        'ExplicitlyLoaded': explicitly_loaded,
    }


def _prepare_releases_root(base_path: Path, work_dir: Path) -> tuple[str, Path]:
    if base_path.is_dir():
        return base_path.name, base_path.parent
    releases_root = work_dir / 'releases'
    if releases_root.exists():
        shutil.rmtree(releases_root)
    _extract_tar_safe(base_path, releases_root)
    candidates = [d for d in releases_root.iterdir() if d.is_dir()]
    if len(candidates) == 1:
        return candidates[0].name, releases_root
    return BASE_RELEASE_NAME, releases_root


def _read_engine_version(engine_root: Path) -> dict[str, str]:
    version_file = engine_root / 'Engine' / 'Build' / 'Build.version'
    if version_file.is_file():
        data = json.loads(version_file.read_text(encoding='utf-8'))
        ver = f'{data.get("MajorVersion", 5)}.{data.get("MinorVersion", 8)}.{data.get("PatchVersion", 0)}'
        return {'version': ver, 'commit': str(data.get('BranchName') or '')}
    return {'version': '5.8.0', 'commit': ''}


def pack_map(
    env: MapEnvironment,
    map_name: str,
    *,
    pack_name: str | None = None,
    out_dir: Path | None = None,
    base_release: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """直接调用 UE RunUAT.bat 仅烘焙目标单张地图，组装并输出标准 .tar.gz 内容包。"""
    if env.project is None or not env.project.is_file():
        raise MapToolError('未配置有效的 CarlaUnreal.uproject 路径')
    if env.engine_root is None:
        raise MapToolError(
            '未配置有效的 Unreal Engine 根目录', hint='请通过 --engine-root 或 machine.toml 配置'
        )
    runuat = env.engine_root / 'Engine' / 'Build' / 'BatchFiles' / 'RunUAT.bat'
    if not runuat.is_file():
        raise MapToolError(f'找不到 RunUAT.bat：{runuat}')

    short_map = map_name.rsplit('/', 1)[-1]
    map_package = map_name if map_name.startswith('/Game/') else f'/Game/Carla/Maps/{short_map}'
    resolved_pack = pack_name or short_map
    resolved_base = resolve_base_release(env, base_release)
    resolved_out = (
        out_dir
        if out_dir is not None
        else (env.carla_root / 'Build' / 'Package' if env.carla_root else Path.cwd())
    )
    resolved_out.mkdir(parents=True, exist_ok=True)

    pack_dir = env.project.parent / 'Plugins' / 'Packs' / resolved_pack
    uplugin_path = pack_dir / f'{resolved_pack}.uplugin'
    work_dir = CACHE_ROOT / 'maps' / f'pack-work-{resolved_pack}'
    staging_dir = work_dir / 'staged'

    release_name, releases_root = _prepare_releases_root(resolved_base, work_dir)
    expected_tar = resolved_out / f'{resolved_pack}-1.0-{release_name}.tar.gz'

    cmd = [
        str(runuat),
        'BuildCookRun',
        f'-project={env.project}',
        '-nocompile',
        '-nocompileeditor',
        '-nop4',
        '-skipbuild',
        '-cook',
        '-stage',
        '-pak',
        '-iostore',
        '-clientconfig=Shipping',
        '-TargetPlatform=Win64',
        '-Platform=Win64',
        f'-dlcname={uplugin_path}',
        f'-basedonreleaseversion={release_name}',
        f'-basedonreleaseversionroot={releases_root}',
        f'-stagingdirectory={staging_dir}',
        f'-AdditionalCookerOptions=-EnablePlugins={resolved_pack}',
        f'-MapsToCook={map_package}',
        '-DLCIncludeEngineContent',
    ]

    if dry_run:
        print('将执行 UAT 单图烘焙命令：')
        print('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        return expected_tar

    # 准备 DLC 插件描述文件（Cook 阶段需 ExplicitlyLoaded=false，打包分发时翻为 true）
    pack_dir.mkdir(parents=True, exist_ok=True)
    uplugin_path.write_text(
        json.dumps(_uplugin_descriptor(resolved_pack, explicitly_loaded=False), indent=2) + '\n',
        encoding='utf-8',
    )
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    log_path = CACHE_ROOT / 'maps' / f'pack-{resolved_pack}.log'
    try:
        code, _, tail = run_logged_command(cmd, log_path, cwd=env.project.parent)
    finally:
        uplugin_path.write_text(
            json.dumps(_uplugin_descriptor(resolved_pack, explicitly_loaded=True), indent=2) + '\n',
            encoding='utf-8',
        )

    if code != 0:
        detail = '\n'.join(tail[-25:])
        raise MapToolError(
            f'地图包烘焙失败（退出码 {code}）：\n{detail}',
            hint=f'完整日志：{log_path}',
        )

    # 定位暂存的 Pak/UTOC/UCAS 与 Cooked AssetRegistry.bin
    staged_paks_candidates = [
        p
        for p in staging_dir.rglob('Windows')
        if p.is_dir() and p.parent.name == 'Paks' and any(p.glob('*.pak'))
    ]
    if not staged_paks_candidates:
        raise MapToolError(f'烘焙完成但未找到输出的 .pak/.utoc/.ucas：{staging_dir}')
    staged_paks = staged_paks_candidates[0]

    registry_src = (
        pack_dir
        / 'Saved'
        / 'Cooked'
        / 'Windows'
        / 'CarlaUnreal'
        / 'Plugins'
        / 'Packs'
        / resolved_pack
        / 'AssetRegistry.bin'
    )
    if not registry_src.is_file():
        candidates = list(pack_dir.rglob('AssetRegistry.bin'))
        if not candidates:
            raise MapToolError(f'找不到烘焙生成的 AssetRegistry.bin：{pack_dir}')
        registry_src = candidates[0]

    # 组装标准分发目录并生成 carla-pack.json 与 .tar.gz
    out_pack = work_dir / 'dist' / resolved_pack
    if out_pack.exists():
        shutil.rmtree(out_pack)
    out_paks = out_pack / 'Content' / 'Paks' / 'Windows'
    out_paks.mkdir(parents=True)

    for ext in ('*.pak', '*.ucas', '*.utoc'):
        for src in staged_paks.glob(ext):
            shutil.copy2(src, out_paks / src.name)

    shutil.copy2(registry_src, out_pack / 'AssetRegistry.bin')
    (out_pack / f'{resolved_pack}.uplugin').write_text(
        json.dumps(_uplugin_descriptor(resolved_pack, explicitly_loaded=True), indent=2) + '\n',
        encoding='utf-8',
    )

    xodr_rel: str | None = None
    if env.content_dir is not None:
        xodr_src = env.content_dir / 'Maps' / 'OpenDrive' / f'{short_map}.xodr'
        if xodr_src.is_file():
            xodr_dst = out_pack / 'Content' / 'Maps' / 'OpenDrive' / xodr_src.name
            xodr_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(xodr_src, xodr_dst)
            xodr_rel = f'Maps/OpenDrive/{xodr_src.name}'

    files_map: dict[str, str] = {}
    for f in sorted(out_pack.rglob('*')):
        if f.is_file():
            files_map[f.relative_to(out_pack).as_posix()] = _sha256_file(f)

    map_entry: JsonObject = {
        'name': short_map,
        'package': map_package,
        'world_partition': False,
    }
    if xodr_rel is not None:
        map_entry['xodr'] = xodr_rel

    manifest = {
        'name': resolved_pack,
        'version': '1.0',
        'carla_version': '1.0',
        'base_release': release_name,
        'engine': _read_engine_version(env.engine_root),
        'platform': 'Windows',
        'maps': [map_entry],
        'catalogs': [],
        'files': files_map,
    }
    (out_pack / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )

    with tarfile.open(expected_tar, 'w:gz') as tar:
        tar.add(out_pack, arcname=resolved_pack)
    return expected_tar
