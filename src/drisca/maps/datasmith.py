"""RoadRunner .udatasmith / .zip 导出文件的解析与路网提取（纯标准库，不依赖 UE）。"""

import json
import math
import re
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

from drisca.maps.models import DatasmithExtract, MapToolError

SEGMENT_TO_CARLA: dict[str, str] = {
    'uncategorized': 'None',
    'road': 'Road',
    'sidewalk': 'SideWalk',
    'curb': 'SideWalk',
    'gutter': 'Road',
    'marking': 'RoadLine',
    'ground': 'Ground',
    'building': 'Building',
    'vehicle': 'Vehicles',
    'bike': 'Vehicles',
    'pedestrian': 'Pedestrian',
    'sign': 'TrafficSign',
    'signal': 'TrafficLight',
    'foliage': 'Vegetation',
    'prop': 'Other',
    'bridge': 'Bridge',
    'terrain': 'Terrain',
    'undefined': 'None',
}

_OPENDRIVE_HINT = re.compile(r'<OpenDRIVE\b', re.IGNORECASE)
_HEADER_HINT = re.compile(r'<header\b[^>]*revMajor', re.IGNORECASE)
_CROSSWALK_OBJECT = re.compile(
    r'(<object\b[^>]*?name="[^"]*[Cc]rosswalk[^"]*"[^>]*?)\stype="[^"]*"',
    re.DOTALL,
)


def _iter_texts(elem: ET.Element) -> Iterator[str]:
    yield from elem.attrib.values()
    if elem.text and elem.text.strip():
        yield elem.text


def _normalise_segment(value: str) -> str | None:
    key = value.strip().lower()
    if key in SEGMENT_TO_CARLA:
        return SEGMENT_TO_CARLA[key]
    if key.endswith('sign'):
        return 'TrafficSign'
    return None


def _target_name(elem: ET.Element) -> str | None:
    reference = elem.attrib.get('reference')
    if reference:
        return reference.split('.', 1)[1] if '.' in reference else reference
    name = elem.attrib.get('name')
    return name if name and name != 'segmentation' else None


def find_opendrive(root: ET.Element) -> tuple[str | None, int]:
    """从 .udatasmith XML 中提取最完整的内嵌 OpenDRIVE 文本。"""
    best: str | None = None
    for elem in root.iter():
        for value in _iter_texts(elem):
            if len(value) < 256:
                continue
            if _OPENDRIVE_HINT.search(value) or _HEADER_HINT.search(value):
                if best is None or len(value) > len(best):
                    best = value
    return best, (len(best.encode('utf-8')) if best else 0)


def find_segmentations(root: ET.Element) -> tuple[dict[str, str], list[str]]:
    """从 .udatasmith XML 中提取网格名到 CARLA 语义目录的映射。"""
    found: dict[str, str] = {}
    actor_level: dict[str, str] = {}
    warnings: list[str] = []

    for elem in root.iter():
        for child in elem:
            prop_name = (child.attrib.get('name') or '').lower()
            if 'segmentation' not in prop_name:
                continue
            raw = child.attrib.get('val') or (child.text or '')
            semantic = _normalise_segment(raw)
            name = _target_name(elem)
            if not semantic or not name:
                continue
            if 'actorsegmentation' in prop_name:
                actor_level[name] = semantic
            else:
                found[name] = semantic

        name = elem.attrib.get('name') or elem.attrib.get('Name')
        if name and name != 'segmentation' and 'reference' not in elem.attrib:
            for key, value in elem.attrib.items():
                if 'segment' in key.lower() or key.lower() in {'type', 'category'}:
                    semantic = _normalise_segment(value)
                    if semantic:
                        found.setdefault(name, semantic)
                        break

    for name, semantic in actor_level.items():
        found.setdefault(name, semantic)

    if not found:
        warnings.append('未解析出网格语义标签，网格将保留在 /Game/RRImport/<地图名>/。')
    return found, warnings


def normalize_crosswalks(xodr_text: str) -> tuple[str, int]:
    """将 RoadRunner 导出的斑马线对象类型规范为 CARLA 识别的 type="crosswalk"。"""
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f'{match.group(1)} type="crosswalk"'

    return _CROSSWALK_OBJECT.sub(_replace, xodr_text), count


def compute_xodr_bounds(xodr_text: str) -> tuple[float, float, float, float, float, float] | None:
    """基于 OpenDRIVE planView 几何端点估算地图边界（米，含 50 m 外扩余量）。"""
    try:
        root = ET.fromstring(xodr_text)
    except ET.ParseError:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for geom in root.iter('geometry'):
        try:
            x = float(geom.attrib['x'])
            y = float(geom.attrib['y'])
            hdg = float(geom.attrib.get('hdg', '0'))
            length = float(geom.attrib.get('length', '0'))
        except KeyError, ValueError:
            continue
        xs.append(x)
        ys.append(-y)
        if length > 0:
            xs.append(x + math.cos(hdg) * length)
            ys.append(-(y + math.sin(hdg) * length))

    if not xs:
        return None
    margin = 50.0
    return (
        min(xs) - margin,
        min(ys) - margin,
        -20.0,
        max(xs) + margin,
        max(ys) + margin,
        80.0,
    )


def locate_scene(path: Path, work_dir: Path, *, full: bool = True) -> Path:
    """定位 .udatasmith 文件；输入为 .zip 时自动安全解压。"""
    if not path.is_file():
        raise MapToolError(f'找不到导出文件：{path}')
    if path.suffix.lower() != '.zip':
        return path.resolve()

    target = work_dir / 'scene'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()

    with zipfile.ZipFile(path) as archive:
        members = [
            item
            for item in archive.infolist()
            if item.filename.lower().endswith('.udatasmith') and not item.filename.startswith('__MACOSX')
        ]
        if len(members) != 1:
            names = ', '.join(item.filename for item in members) or '无'
            raise MapToolError(
                f'压缩包内应有且只有一个 .udatasmith 文件，实际发现 {len(members)} 个（{names}）',
                hint='请确认 RoadRunner 导出格式为 Unreal Datasmith（.udatasmith 或 .zip）',
            )
        only_xml = {members[0].filename}
        for item in archive.infolist():
            if item.is_dir() or item.filename.startswith('__MACOSX'):
                continue
            if not full and item.filename not in only_xml:
                continue
            destination = (target / item.filename).resolve()
            if target_resolved not in destination.parents:
                raise MapToolError(f'压缩包包含非法路径：{item.filename}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, destination.open('wb') as dst:
                shutil.copyfileobj(src, dst)

    scene = (target / members[0].filename).resolve()
    if not scene.is_file():
        raise MapToolError(f'解压后未找到目标场景文件：{members[0].filename}')
    return scene


def extract_datasmith(scene: Path, out_dir: Path, map_name: str) -> DatasmithExtract:
    """解析 .udatasmith，写出 <map_name>.xodr 与 segmentation.json。"""
    if not scene.is_file():
        raise MapToolError(f'找不到场景文件：{scene}')
    try:
        root = ET.parse(scene).getroot()
    except ET.ParseError as exc:
        raise MapToolError(f'Datasmith XML 解析失败：{exc}') from exc

    xodr_raw, xodr_bytes = find_opendrive(root)
    segments, warnings = find_segmentations(root)

    out_dir.mkdir(parents=True, exist_ok=True)
    xodr_path: Path | None = None
    crosswalk_count = 0
    bounds_m: tuple[float, float, float, float, float, float] | None = None
    if xodr_raw is not None:
        xodr_clean, crosswalk_count = normalize_crosswalks(xodr_raw)
        bounds_m = compute_xodr_bounds(xodr_clean)
        xodr_path = out_dir / f'{map_name}.xodr'
        xodr_path.write_text(xodr_clean, encoding='utf-8')
    else:
        warnings.append('未在 .udatasmith 中找到内嵌 OpenDRIVE 路网。')

    seg_path = out_dir / 'segmentation.json'
    seg_path.write_text(
        json.dumps({'map': map_name, 'meshes': segments}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    return DatasmithExtract(
        scene_path=scene.resolve(),
        map_name=map_name,
        xodr_path=xodr_path,
        xodr_bytes=xodr_bytes,
        crosswalk_count=crosswalk_count,
        segmentation_path=seg_path,
        mesh_count=len(segments),
        bounds_m=bounds_m,
        warnings=tuple(warnings),
    )
