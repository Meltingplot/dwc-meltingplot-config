#!/usr/bin/env bash
#
# Run the GitHub Actions CI pipeline (.github/workflows/ci.yml) locally.
#
# Everything is kept inside .ci-local/ (gitignored):
#   .ci-local/venv            Python virtualenv with pytest + pytest-cov
#   .ci-local/DuetWebControl  DuetWebControl checkout used for the plugin build
#   .ci-local/dist            built plugin ZIP, copied out of the DWC tree
#
# Nothing is installed globally and the system Python/Node are left untouched.
#
# Usage:
#   scripts/ci-local.sh [stage ...]
#
# Stages:
#   python      pytest (venv, host Python)
#   matrix      pytest on Python 3.9/3.10/3.11/3.12 via Docker (full CI matrix)
#   frontend    npm ci + lint + jest unit + jest integration
#   build       DuetWebControl checkout + build-plugin -> plugin ZIP
#   all         python + frontend + build  (default)
#
# Env overrides:
#   DWC_REF=v3.6-dev   DuetWebControl branch/tag to build against
#   PYTHON=python3     interpreter used to create the venv

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/.ci-local"
VENV="$WORK/venv"
DWC_DIR="$WORK/DuetWebControl"
DWC_REF="${DWC_REF:-v3.6-dev}"
PYTHON="${PYTHON:-python3}"
PY_MATRIX=(3.9 3.10 3.11 3.12)

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$WORK"

stage_python() {
    step "Python tests (venv, $($PYTHON -V))"
    if [ ! -x "$VENV/bin/python" ]; then
        "$PYTHON" -m venv "$VENV"
    fi
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet pytest pytest-cov
    cd "$ROOT"
    PYTHONPATH=dsf "$VENV/bin/python" -m pytest tests/ -v --tb=short --cov --cov-report=term-missing
    ok "Python tests passed"
}

stage_matrix() {
    step "Python matrix via Docker (${PY_MATRIX[*]})"
    command -v docker >/dev/null || die "docker not available"
    for v in "${PY_MATRIX[@]}"; do
        step "Python $v (docker)"
        docker run --rm \
            -v "$ROOT:/src:ro" \
            -w /tmp/work \
            -e PYTHONPATH=dsf \
            "python:$v-slim" \
            bash -c 'set -e
                     # the slim images ship without git, which the tests shell out to;
                     # CI runners have it preinstalled
                     apt-get -qq update && apt-get -qq install -y --no-install-recommends git >/dev/null
                     cp -r /src/. /tmp/work
                     rm -rf /tmp/work/.ci-local /tmp/work/node_modules
                     find /tmp/work -name __pycache__ -type d -prune -exec rm -rf {} +
                     pip install --quiet --root-user-action=ignore pytest pytest-cov
                     pytest tests/ -v --tb=short --cov --cov-report=term-missing' \
            || die "Python $v failed"
    done
    ok "Python matrix passed"
}

stage_frontend() {
    step "Frontend lint & tests (node $(node -v))"
    cd "$ROOT"
    npm ci
    npm run lint
    npx jest tests/frontend/*.test.js --verbose
    npx jest tests/frontend/integration/ --verbose
    ok "Frontend lint & tests passed"
}

stage_build() {
    step "Build plugin ZIP (DuetWebControl $DWC_REF)"
    if [ -d "$DWC_DIR/.git" ]; then
        git -C "$DWC_DIR" fetch --depth 1 origin "$DWC_REF"
        git -C "$DWC_DIR" checkout --force FETCH_HEAD
    else
        git clone --depth 1 --branch "$DWC_REF" \
            https://github.com/Duet3D/DuetWebControl.git "$DWC_DIR"
    fi

    step "Install DuetWebControl dependencies"
    (cd "$DWC_DIR" && npm install)

    # build-plugin packages everything under dsf/, so byte-code left behind by
    # the python stage would end up in the ZIP. CI builds a fresh checkout and
    # never has these — drop them so the local ZIP matches the CI artifact.
    find "$ROOT/dsf" -name '__pycache__' -type d -prune -exec rm -rf {} +

    # version.js --write patches plugin.json/package.json; CI does this on a
    # throwaway checkout, so locally we snapshot and restore them afterwards.
    local backup="$WORK/version-backup"
    mkdir -p "$backup"
    cp "$ROOT/plugin.json" "$ROOT/package.json" "$backup/"
    restore_version() { cp "$backup/plugin.json" "$backup/package.json" "$ROOT/"; }
    trap restore_version EXIT

    step "Compute version from git"
    (cd "$ROOT" && node scripts/version.js --write)

    step "Run build-plugin"
    (cd "$DWC_DIR" && npm run build-plugin "$ROOT")

    restore_version
    trap - EXIT

    local zip
    zip="$(ls -1 "$DWC_DIR"/dist/MeltingplotConfig-*.zip 2>/dev/null | head -1)" \
        || die "no plugin ZIP produced"
    [ -n "$zip" ] || die "no plugin ZIP produced"

    mkdir -p "$WORK/dist"
    cp "$zip" "$WORK/dist/"
    step "Plugin ZIP contents"
    unzip -l "$zip"
    ok "Built $(basename "$zip") -> .ci-local/dist/"
}

stages=("$@")
[ ${#stages[@]} -eq 0 ] && stages=(all)
for s in "${stages[@]}"; do
    case "$s" in
        all)      stage_python; stage_frontend; stage_build ;;
        python)   stage_python ;;
        matrix)   stage_matrix ;;
        frontend) stage_frontend ;;
        build)    stage_build ;;
        *)        die "unknown stage: $s (python|matrix|frontend|build|all)" ;;
    esac
done

printf '\n'
ok "CI run complete: ${stages[*]}"
