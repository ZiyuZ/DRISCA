"""地图导入、烘焙与内容包管理的数据模型。"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class MapToolError(RuntimeError):
    """地图工具执行错误。"""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class MapEnvironment(BaseModel):
    """地图制作与安装所需的本地路径集合。"""

    model_config = ConfigDict(frozen=True)

    carla_root: Path | None = None
    project: Path | None = None
    engine_root: Path | None = None
    editor_executable: Path | None = None
    editor_cmd_executable: Path | None = None
    packaged_dir: Path | None = None
    base_release: Path | None = None

    @property
    def carla_pack_script(self) -> Path | None:
        if self.carla_root is None:
            return None
        return self.carla_root / 'Util' / 'ContentPacks' / 'carla_pack.py'

    @property
    def content_dir(self) -> Path | None:
        if self.project is None:
            return None
        return self.project.parent / 'Content' / 'Carla'


class CheckItem(BaseModel):
    """环境自检单项结果。"""

    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    detail: str


class DatasmithExtract(BaseModel):
    """从 .udatasmith 提取的路网与语义摘要。"""

    model_config = ConfigDict(frozen=True)

    scene_path: Path
    map_name: str
    xodr_path: Path | None
    xodr_bytes: int
    crosswalk_count: int
    segmentation_path: Path
    mesh_count: int
    bounds_m: tuple[float, float, float, float, float, float] | None
    warnings: tuple[str, ...]


class PackInfo(BaseModel):
    """独立地图内容包清单摘要。"""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    maps: tuple[str, ...]
    path: Path
