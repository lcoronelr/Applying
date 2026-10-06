#!/bin/bash
# One-time setup. Double-click (first time: right-click → Open).
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python is missing — install it from https://www.python.org/downloads/ and run this again."; read -r; exit 1; }
command -v npm >/dev/null || { echo "Node.js is missing — install the LTS version from https://nodejs.org and run this again."; read -r; exit 1; }
echo "Setting up Python packages…"
python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
echo "Setting up the app (this downloads ~150 MB once)…"
(cd app && npm install --silent)
echo
echo "All set! Double-click Apply.command to open the app."
read -r -p "Press Enter to close."
