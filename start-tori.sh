#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_ROOT=$SCRIPT_DIRECTORY
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '%s\n' \
        "ERROR: Tori's Python environment is missing. Run ./install.sh from $PROJECT_ROOT first." \
        >&2
    exit 1
fi

cd "$PROJECT_ROOT"
unset PYTHONHOME
export PYTHONPATH="$PROJECT_ROOT/src"

printf '%s\n' "Starting Tori's web interface..."
printf '%s\n' 'Press Ctrl+C here to stop Tori.'
exec "$VENV_PYTHON" -m tori --web
