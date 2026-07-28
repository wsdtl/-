#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON_BIN=${PYTHON_BIN:-python}
NEEDS_INSTALL=0

if [ ! -x "$VENV_PYTHON" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    NEEDS_INSTALL=1
fi

if ! "$VENV_PYTHON" -c \
    'import apscheduler, cryptography, fastapi, loguru, urllib3, uvicorn' \
    >/dev/null 2>&1; then
    NEEDS_INSTALL=1
fi

if [ "$NEEDS_INSTALL" -eq 1 ]; then
    "$VENV_PYTHON" -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        -r "$PROJECT_ROOT/requirements.txt"
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec "$VENV_PYTHON" main.py
