#!/usr/bin/env bash
# Build the Arco macOS installer (dist/Arco-<version>-arm64.dmg) on this Mac.
# Needs Homebrew python@3.10, node and unixodbc; Python deps go into <repo>/.venv.
set -euo pipefail

FRONTEND_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(dirname "$FRONTEND_ROOT")"
cd "$FRONTEND_ROOT"

export PYTHON_EXE="${PYTHON_EXE:-$REPO_ROOT/.venv/bin/python}"
"$PYTHON_EXE" build/check_python_build_env.py

# The Windows build's helper writes this wheel; electron-builder ships it as a resource.
node build/helpers/build_python_api_wheel.js

"$PYTHON_EXE" -m PyInstaller build/server.spec --distpath python_dist --workpath python_build --noconfirm
test -x python_dist/arcrho_server/arcrho_server
test -f python_dist/arcrho_server/_internal/ui/index.html
"$PYTHON_EXE" build/write_backend_artifact_manifest.py python_dist/arcrho_server

# macOS wants a 512px+ app icon; the tracked icon.png is 256px.
mkdir -p build/generated/mac-icon
sips -z 1024 1024 icons/icon.png --out build/generated/mac-icon/icon.png >/dev/null

[ -d node_modules ] || npm ci
npx electron-builder --mac

rm -rf python_dist python_build
git checkout -- build/python_packages
ls -lh dist/*.dmg
