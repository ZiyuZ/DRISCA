"""允许通过 `uv run -m drisca.maps` 调用地图工具。"""

from drisca.maps.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
