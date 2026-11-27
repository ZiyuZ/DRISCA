"""独立地图内容包（.tar.gz）的校验、安装、查询、卸载与烘焙调度。"""

import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections import deque
from pathlib import Path

from drisca.core.paths import CACHE_ROOT
from drisca.maps.models import MapEnvironment, MapToolError, PackInfo

BASE_RELEASE_NAME = 'carla-1.0-Win64'


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


def read_pack_manifest(pack_file: Path) -> PackInfo:
    """从 .tar.gz 地图包中读取 carla-pack.json 清单摘要。"""
    if not pack_file.is_file():
        raise MapToolError(f'找不到地图包文件：{pack_file}')
    try:
        with tarfile.open(pack_file, 'r:*') as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                if member.name.replace('\\', '/').endswith('carla-pack.json'):
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
    raise MapToolError(f'地图包中缺少 carla-pack.json：{pack_file}')


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
        manifest = entry / 'carla-pack.json'
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


def _resolve_pack_script(server_dir: Path | None, carla_root: Path | None) -> Path:
    if server_dir is not None:
        packaged_script = server_dir / 'Tools' / 'carla_pack.py'
        if packaged_script.is_file():
            return packaged_script
    if carla_root is not None:
        source_script = carla_root / 'Util' / 'ContentPacks' / 'carla_pack.py'
        if source_script.is_file():
            return source_script
    raise MapToolError(
        '找不到 carla_pack.py 工具脚本',
        hint='请确认 Shipping 目录下存在 Tools/carla_pack.py，或通过 --carla-root 指定 CARLA 源码目录',
    )


def verify_pack(
    pack_file: Path,
    *,
    server_dir: Path | None = None,
    carla_root: Path | None = None,
) -> PackInfo:
    """校验地图包完整性并返回清单摘要。"""
    info = read_pack_manifest(pack_file)
    script = _resolve_pack_script(server_dir, carla_root)
    log_path = CACHE_ROOT / 'maps' / f'verify-{info.name}.log'
    code, _, tail = run_logged_command(
        [sys.executable, str(script), 'verify', str(pack_file)],
        log_path,
        echo=False,
    )
    if code != 0:
        detail = '\n'.join(tail[-20:])
        raise MapToolError(
            f'地图包校验失败（退出码 {code}）：\n{detail}',
            hint=f'完整日志：{log_path}',
        )
    return info


def install_pack(
    pack_file: Path,
    server_dir: Path,
    *,
    force: bool = False,
    carla_root: Path | None = None,
) -> PackInfo:
    """校验并将独立地图包安装到 Shipping 基础包的 CarlaUnreal/Packs/ 目录。"""
    if not server_dir.is_dir():
        raise MapToolError(f'Shipping 服务器目录不存在：{server_dir}')
    info = verify_pack(pack_file, server_dir=server_dir, carla_root=carla_root)
    script = _resolve_pack_script(server_dir, carla_root)

    cmd = [sys.executable, str(script), 'install', str(pack_file), '--server', str(server_dir)]
    installed_dir = server_dir / 'CarlaUnreal' / 'Packs' / info.name
    if force or installed_dir.is_dir():
        cmd.append('--force')

    log_path = CACHE_ROOT / 'maps' / f'install-{info.name}.log'
    code, _, tail = run_logged_command(cmd, log_path, cwd=server_dir)
    if code != 0:
        detail = '\n'.join(tail[-20:])
        raise MapToolError(
            f'地图包安装失败（退出码 {code}）：\n{detail}',
            hint=f'完整日志：{log_path}（请先确认 CARLA 进程未在运行）',
        )
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
        hint='请先完成一次 Shipping 基础包打包，或通过 --base 指定 carla-1.0-Win64-release-metadata.tar.gz',
    )


def pack_map(
    env: MapEnvironment,
    map_name: str,
    *,
    pack_name: str | None = None,
    out_dir: Path | None = None,
    base_release: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """基于基础包元数据，将指定地图烘焙为独立 .tar.gz 内容包。"""
    if env.project is None or not env.project.is_file():
        raise MapToolError('未配置有效的 CarlaUnreal.uproject 路径')
    script = env.carla_pack_script
    if script is None or not script.is_file():
        raise MapToolError('找不到 Util/ContentPacks/carla_pack.py')

    resolved_pack = pack_name or map_name
    resolved_base = resolve_base_release(env, base_release)
    resolved_out = (
        out_dir
        if out_dir is not None
        else (env.carla_root / 'Build' / 'Package' if env.carla_root else Path.cwd())
    )
    resolved_out.mkdir(parents=True, exist_ok=True)

    map_package = map_name if map_name.startswith('/Game/') else f'/Game/Carla/Maps/{map_name}'
    cmd = [
        sys.executable,
        str(script),
        'create',
        resolved_pack,
        map_package,
        '--project',
        str(env.project),
        '--base',
        str(resolved_base),
        '--config',
        'Shipping',
        '--platform',
        'Win64',
        '--pack-version',
        '1.0',
        '--out',
        str(resolved_out),
    ]
    if env.engine_root is not None:
        cmd.extend(['--engine', str(env.engine_root)])

    expected_output = resolved_out / f'{resolved_pack}-1.0-{BASE_RELEASE_NAME}.tar.gz'
    if dry_run:
        print('将执行命令：')
        print('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        return expected_output

    log_path = CACHE_ROOT / 'maps' / f'pack-{resolved_pack}.log'
    code, _, tail = run_logged_command(
        cmd,
        log_path,
        cwd=env.carla_root / 'Build' if env.carla_root else None,
    )
    if code != 0:
        detail = '\n'.join(tail[-25:])
        raise MapToolError(
            f'地图包烘焙失败（退出码 {code}）：\n{detail}',
            hint=f'完整日志：{log_path}',
        )
    return expected_output
