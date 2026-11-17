#!/usr/bin/env bash
# Start the desktop simulator from any working directory.
set -euo pipefail
EMULATION="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$EMULATION/.."

PYTHON="${PYTHON:-python3}"
VENV="$EMULATION/.venv-simulator"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 is required. Install python3, python3-venv and python3-tk." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
  echo "Python tkinter is missing. On Ubuntu/Debian: sudo apt install python3-tk" >&2
  exit 1
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating simulator virtual environment..."
  "$PYTHON" -m venv "$VENV" || {
    echo "Could not create a venv. On Ubuntu/Debian: sudo apt install python3-venv" >&2
    exit 1
  }
fi
if ! "$VENV/bin/python" -c 'import PIL, mutagen, fontTools, unicorn, elftools' >/dev/null 2>&1; then
  echo "Installing simulator Python dependencies..."
  "$VENV/bin/python" -m pip install -r "$EMULATION/requirements-simulator.txt"
fi
exec "$VENV/bin/python" "$EMULATION/simulator.py" "$@"
