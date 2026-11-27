# 安装 just: winget install --id Casey.Just

version := `uv version --short`

default:
    @just --list

# =====================
#        开发
# =====================
rumdl *paths=".":
    rumdl check {{ paths }}
lint:
    uv run ruff format --check src
    uv run ruff check src
    uv run ty check src

frontend-dev:
    bun run --cwd frontend dev

frontend-check:
    bun run --cwd frontend typecheck

frontend-build:
    bun run --cwd frontend build

launcher *args:
    uv run -m drisca.launcher {{ args }}

maps *args:
    uv run -m drisca.maps {{ args }}

docs-dev:
    bun run --cwd .github/docs-site docs:dev

docs-build:
    bun run --cwd .github/docs-site docs:build

# =====================
#        发布
# =====================
bump part="patch":
    uv version --bump {{ part }} --no-sync

tag:
    git tag -a "v{{ version }}" -m "v{{ version }}"
