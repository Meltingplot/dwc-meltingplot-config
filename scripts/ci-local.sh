#!/usr/bin/env bash
#
# Run the GitHub Actions CI pipeline (.github/workflows/ci.yml) locally.
#
# Everything is kept inside .ci-local/ (gitignored):
#   .ci-local/venv                 Python virtualenv with pytest + pytest-cov
#   .ci-local/DuetWebControl       DWC 3.6 checkout used for the 3.6 package
#   .ci-local/DuetWebControl-3.7   DWC 3.7 checkout used for the 3.7 package
#   .ci-local/dist                 built plugin ZIPs
#
# Nothing is installed globally and the system Python/Node are left untouched.
#
# Usage:
#   scripts/ci-local.sh [stage ...]
#
# Stages:
#   python      pytest (venv, host Python)
#   matrix      pytest on Python 3.10/3.11/3.12 via Docker (full CI matrix)
#   frontend    npm ci + lint + jest unit + jest integration
#   ui37        Vitest: DWC 3.7 components + the shared core under Vue 3
#   build36     DWC 3.6 checkout + build.js 36 -> ...-dwc36.zip
#   build37     DWC 3.7 checkout + build.js 37 -> ...-dwc37.zip (needs Node 22+)
#   build       build36 + build37
#   all         python + frontend + ui37 + build  (default)
#
# The 3.7 toolchain (Vite 8 / TypeScript 6) needs Node 22+. When the host Node
# is older, build37 runs inside a node:22 Docker container instead.
#
# Env overrides:
#   DWC36_REF=v3.6-dev  DuetWebControl ref for the 3.6 package
#   DWC37_REF=v3.7-dev  DuetWebControl ref for the 3.7 package
#   PYTHON=python3      interpreter used to create the venv

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/.ci-local"
VENV="$WORK/venv"
DWC36_DIR="$WORK/DuetWebControl"
DWC37_DIR="$WORK/DuetWebControl-3.7"
DWC36_REF="${DWC36_REF:-v3.6-dev}"
DWC37_REF="${DWC37_REF:-v3.7-dev}"
PYTHON="${PYTHON:-python3}"
PY_MATRIX=(3.10 3.11 3.12)
# Node major the DWC 3.7 toolchain (Vite 8 / TS 6) needs
NODE37_MIN=22

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
    npx jest tests/frontend/*.test.js tests/frontend/core/ --verbose
    npx jest tests/frontend/integration/ --verbose
    ok "Frontend lint & tests passed"
}

stage_ui37() {
    step "DWC 3.7 UI tests (Vue 3 + Vuetify 4)"
    local node_major
    node_major="$(node -p 'process.versions.node.split(".")[0]')"

    if [ "$node_major" -ge "$NODE37_MIN" ]; then
        (cd "$ROOT/tests/ui37" && npm ci && npm test)
    else
        command -v docker >/dev/null \
            || die "node $node_major is too old for Vitest here (need $NODE37_MIN+) and docker is not available"
        step "Host node is $node_major — running in a node:$NODE37_MIN container"
        docker run --rm \
            -v "$ROOT:/work" \
            -w /work/tests/ui37 \
            -u "$(id -u):$(id -g)" \
            -e HOME=/tmp \
            -e CI=1 \
            "node:$NODE37_MIN" \
            bash -c 'npm ci && npm test' \
            || die "DWC 3.7 UI tests failed"
    fi
    ok "DWC 3.7 UI tests passed"
}

# Fetch (or update) a DuetWebControl checkout at a given ref.
checkout_dwc() {
    local dir="$1" ref="$2"
    if [ -d "$dir/.git" ]; then
        git -C "$dir" fetch --depth 1 origin "$ref"
        git -C "$dir" checkout --force FETCH_HEAD
    else
        git clone --depth 1 --branch "$ref" \
            https://github.com/Duet3D/DuetWebControl.git "$dir"
    fi
}

# version.js --write patches plugin.json/package.json; CI does this on a
# throwaway checkout, so locally we snapshot and restore them afterwards.
stamp_version() {
    local backup="$WORK/version-backup"
    mkdir -p "$backup"
    cp "$ROOT/plugin.json" "$ROOT/package.json" "$backup/"
    trap 'cp "$WORK/version-backup/plugin.json" "$WORK/version-backup/package.json" "$ROOT/"' EXIT
    (cd "$ROOT" && node scripts/version.js --write)
}

restore_version() {
    cp "$WORK/version-backup/plugin.json" "$WORK/version-backup/package.json" "$ROOT/"
    trap - EXIT
}

# Report and copy out the ZIP one build leg produced.
collect_zip() {
    local gen="$1" zip
    zip="$(ls -1 "$ROOT"/dist/MeltingplotConfig-*-dwc"$gen".zip 2>/dev/null | head -1)"
    [ -n "$zip" ] || die "no DWC 3.${gen:1:1} plugin ZIP produced"

    mkdir -p "$WORK/dist"
    cp "$zip" "$WORK/dist/"
    step "Plugin ZIP contents"
    unzip -l "$zip"

    step "Verify manifest"
    unzip -p "$zip" plugin.json | node -e '
        let raw = "";
        process.stdin.on("data", (chunk) => { raw += chunk; });
        process.stdin.on("end", () => {
            const manifest = JSON.parse(raw);
            const expected = process.argv[1];
            if (manifest.dwcVersion !== expected) {
                console.error(`dwcVersion is ${manifest.dwcVersion}, expected ${expected}`);
                process.exit(1);
            }
            if (!(manifest.dwcFiles || []).some((f) => f.endsWith(".js"))) {
                console.error("dwcFiles carries no JS resource");
                process.exit(1);
            }
            if (!(manifest.dsfFiles || []).includes("meltingplot-config-daemon.py")) {
                console.error("dsfFiles is missing the daemon");
                process.exit(1);
            }
            console.log(`dwcVersion=${manifest.dwcVersion} dwcFiles=${manifest.dwcFiles.join(", ")}`);
        });
    ' "3.${gen:1:1}" || die "manifest verification failed"

    ok "Built $(basename "$zip") -> .ci-local/dist/"
}

stage_build36() {
    step "Build DWC 3.6 package (DuetWebControl $DWC36_REF)"
    checkout_dwc "$DWC36_DIR" "$DWC36_REF"

    step "Install DuetWebControl 3.6 dependencies"
    (cd "$DWC36_DIR" && npm install)

    stamp_version
    step "Run build.js 36"
    (cd "$ROOT" && DWC36_DIR="$DWC36_DIR" node scripts/build.js 36)
    restore_version

    collect_zip 36
}

stage_build37() {
    step "Build DWC 3.7 package (DuetWebControl $DWC37_REF)"
    checkout_dwc "$DWC37_DIR" "$DWC37_REF"

    local node_major
    node_major="$(node -p 'process.versions.node.split(".")[0]')"

    if [ "$node_major" -ge "$NODE37_MIN" ]; then
        step "Install DuetWebControl 3.7 dependencies (node $(node -v))"
        (cd "$DWC37_DIR" && npm install)

        stamp_version
        step "Run build.js 37"
        (cd "$ROOT" && DWC37_DIR="$DWC37_DIR" node scripts/build.js 37)
        restore_version
    else
        # Vite 8 / TypeScript 6 need Node 22+; borrow one from Docker rather
        # than asking the developer to switch their system Node.
        command -v docker >/dev/null \
            || die "node $node_major is too old for the DWC 3.7 toolchain (need $NODE37_MIN+) and docker is not available"
        step "Host node is $node_major — running the 3.7 leg in a node:$NODE37_MIN container"

        stamp_version
        docker run --rm \
            -v "$ROOT:/work" \
            -w /work \
            -u "$(id -u):$(id -g)" \
            -e HOME=/tmp \
            -e DWC37_DIR=/work/.ci-local/DuetWebControl-3.7 \
            "node:$NODE37_MIN" \
            bash -c 'set -e
                     cd "$DWC37_DIR" && npm install --no-audit --no-fund
                     cd /work && node scripts/build.js 37' \
            || { restore_version; die "DWC 3.7 build failed"; }
        restore_version
    fi

    collect_zip 37
}

stage_build() {
    stage_build36
    stage_build37
}

stages=("$@")
[ ${#stages[@]} -eq 0 ] && stages=(all)
for s in "${stages[@]}"; do
    case "$s" in
        all)      stage_python; stage_frontend; stage_ui37; stage_build ;;
        python)   stage_python ;;
        matrix)   stage_matrix ;;
        frontend) stage_frontend ;;
        ui37)     stage_ui37 ;;
        build)    stage_build ;;
        build36)  stage_build36 ;;
        build37)  stage_build37 ;;
        *)        die "unknown stage: $s (python|matrix|frontend|ui37|build|build36|build37|all)" ;;
    esac
done

printf '\n'
ok "CI run complete: ${stages[*]}"
