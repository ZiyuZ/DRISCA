# 安装 just: winget install --id Casey.Just

version := `uv version --short`

default:
    @just --list

# =====================
#        开发
# =====================
rumdl *paths=".":
    rumdl fmt {{ paths }}
    rumdl check --fix {{ paths }}
lint:
    uv run ruff format src
    uv run ruff check --fix src
    uv run ty check src

# =====================
#        发布
# =====================
bump part="patch":
    uv version --bump {{ part }} --no-sync

tag:
    git tag -a "v{{ version }}" -m "v{{ version }}"
