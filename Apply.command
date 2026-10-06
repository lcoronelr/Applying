#!/bin/bash
# Double-click to open the Apply app.
cd "$(dirname "$0")/app" && env -u ELECTRON_RUN_AS_NODE ./node_modules/.bin/electron . >/dev/null 2>&1 &
