#!/bin/bash
# Builds build/release/Apply-<version>-arm64.dmg: the Python engine bundled with PyInstaller + the Electron app.
set -e
cd "$(dirname "$0")"
WORK="$(mktemp -d)"
.venv/bin/python -m pip install -q pyinstaller
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --name engine \
  --distpath build/dist --workpath "$WORK/work" --specpath "$WORK" \
  --collect-data reportlab --collect-all playwright \
  --hidden-import matcher --hidden-import profiles --hidden-import ai \
  --exclude-module pytest --exclude-module tkinter engine.py
cd app
[ -d node_modules ] || npm install
env -u ELECTRON_RUN_AS_NODE npx electron-builder --mac
echo "Done: $(ls ../build/release/*.dmg)"
