#!/usr/bin/env bash
# Start the Q2 Unicorn game emulator using the desktop simulator venv.
set -euo pipefail
EMULATION="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$EMULATION/.."
PYTHON="${PYTHON:-python3}"
VENV="$EMULATION/.venv-simulator"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
if ! "$VENV/bin/python" -c 'import PIL, unicorn, elftools' >/dev/null 2>&1; then
  "$VENV/bin/python" -m pip install -r "$EMULATION/requirements-simulator.txt"
fi
if [[ "${1:-}" != "--self-test" && "${1:-}" != "--snapshot" ]]; then
  "$PYTHON" -c 'import tkinter' || {
    echo "Install tkinter (Ubuntu: sudo apt install python3-tk)" >&2
    exit 1
  }
fi
exec "$VENV/bin/python" "$EMULATION/arcade_emulator.py" "$@"
