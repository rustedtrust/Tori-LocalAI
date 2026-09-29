#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
CONFIG_PATH="$PROJECT_ROOT/tori.toml"
TEMPLATE="$PROJECT_ROOT/deploy/portable/tori.toml"
REQUIREMENTS="$PROJECT_ROOT/requirements.txt"
VENV="$PROJECT_ROOT/.venv"
PYTHON=${TORI_INSTALLER_PYTHON:-python3}
NON_INTERACTIVE=0

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
note() { printf '%s\n' "$1"; }

usage() {
    cat <<'EOF'
Usage: ./install.sh [--non-interactive] [--help]

Install core Tori from a fresh Debian/Ubuntu source tree. Rerunnable before
first start; existing runtime data is never inspected or upgraded.
  --non-interactive  Never prompt or perform privileged actions.
  --help             Show this help and exit.

Voice and Research need separately prepared prerequisites. External model,
search, TTS, Discord and coding-agent services are configured later in Tori.
EOF
}

while (( $# )); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --non-interactive) NON_INTERACTIVE=1 ;;
        *) usage >&2; fail "unsupported installer argument: $1" ;;
    esac
    shift
done

[[ $(uname -s) == Linux && -r /etc/os-release ]] \
    || fail "this installer requires Debian/Ubuntu Linux"
distribution=$(awk -F= '$1 == "ID" || $1 == "ID_LIKE" {
    value=$2; gsub(/^\"|\"$/, "", value); printf "%s ", value
}' /etc/os-release)
case " $distribution " in
    *" debian "*|*" ubuntu "*) ;;
    *) fail "this installer supports Debian/Ubuntu-family Linux only" ;;
esac

for source in "$TEMPLATE" "$REQUIREMENTS" "$PROJECT_ROOT/start-tori.sh"; do
    [[ -f "$source" && ! -L "$source" ]] || fail "missing or unsafe installer input: $source"
done
[[ -d "$PROJECT_ROOT/src/tori" && ! -L "$PROJECT_ROOT/src/tori" ]] \
    || fail "the Tori source package is missing or unsafe"
[[ -x "$PROJECT_ROOT/start-tori.sh" ]] || fail "start-tori.sh is not executable"
[[ -w "$PROJECT_ROOT" ]] || fail "the project directory is not writable"
[[ ! -e "$PROJECT_ROOT/runtime" && ! -L "$PROJECT_ROOT/runtime" ]] \
    || fail "runtime already exists; this fresh-install workflow will not inspect, migrate, replace, or delete it"
if [[ -e "$CONFIG_PATH" || -L "$CONFIG_PATH" ]]; then
    [[ -f "$CONFIG_PATH" && ! -L "$CONFIG_PATH" ]] \
        || fail "tori.toml exists but is not a safe regular file"
fi
[[ ! -L "$VENV" ]] || fail ".venv is a symbolic link; refusing to follow it"
if [[ -e "$VENV" ]]; then
    [[ -d "$VENV" && -f "$VENV/pyvenv.cfg" && -x "$VENV/bin/python" ]] \
        || fail ".venv already exists but is not a valid reusable virtual environment"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1 || \
    ! env -u PYTHONHOME -u PYTHONPATH "$PYTHON" -c 'import sys, venv; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    if (( NON_INTERACTIVE )); then
        fail "python3 is missing or unsupported; install Python 3.11+ and python3-venv, then rerun"
    fi
    note "Core prerequisite: Python 3.11+ with venv. Proposed privileged command: sudo apt-get install --no-install-recommends python3 python3-venv"
    printf '%s' 'Run this exact package installation now? [y/N] '
    IFS= read -r reply || reply=""
    case "$reply" in
        y|Y|yes|Yes|YES) ;;
        *) fail "Python prerequisite installation was declined" ;;
    esac
    command -v sudo >/dev/null && command -v apt-get >/dev/null \
        || fail "sudo/apt-get is unavailable; install Python and venv manually"
    sudo apt-get install --no-install-recommends python3 python3-venv
    env -u PYTHONHOME -u PYTHONPATH "$PYTHON" -c 'import sys, venv; assert sys.version_info >= (3, 11)' \
        || fail "Python 3.11+ with venv remains unavailable"
fi

if [[ -e "$CONFIG_PATH" ]]; then
    note "Preserving the existing local tori.toml; it was not replaced."
else
    temporary=$(mktemp "$PROJECT_ROOT/.tori.toml.install.XXXXXX") \
        || fail "could not create a temporary local configuration"
    chmod 0600 "$temporary"
    if ! cp -- "$TEMPLATE" "$temporary" || \
        ! env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PROJECT_ROOT/src" \
            "$PYTHON" - "$temporary" <<'PY'
from pathlib import Path
import sys
from tori.config import load_settings
load_settings(Path(sys.argv[1]), environ={})
PY
    then
        rm -f -- "$temporary"
        fail "the portable configuration template did not pass Tori validation"
    fi
    # Publish a complete validated file only if no other process won the name.
    if ! ln -- "$temporary" "$CONFIG_PATH"; then
        rm -f -- "$temporary"
        fail "tori.toml appeared during configuration setup; it was not overwritten"
    fi
    rm -f -- "$temporary"
    note "Created local tori.toml from deploy/portable/tori.toml."
fi

if [[ -e "$VENV" ]]; then
    note "Reusing the existing valid .venv; it was not replaced."
else
    note "Creating the project virtual environment at $VENV"
    env -u PYTHONHOME -u PYTHONPATH "$PYTHON" -m venv "$VENV" \
        || fail "virtual-environment creation failed; inspect any partial .venv before rerunning"
fi
env -u PYTHONHOME -u PYTHONPATH "$VENV/bin/python" -c 'import sys; assert sys.version_info >= (3, 11)' \
    || fail "the project virtual environment uses unsupported Python"
env -u PYTHONHOME -u PYTHONPATH "$VENV/bin/python" -m pip --version >/dev/null \
    || fail "pip is unavailable inside .venv"
note "Installing Tori's declared requirements in its own environment."
env -u PYTHONHOME -u PYTHONPATH "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$REQUIREMENTS" \
    || fail "Python dependency installation failed; review pip's diagnostics above"
env -u PYTHONHOME -u PYTHONPATH "$VENV/bin/python" -m pip check \
    || fail "Python dependency integrity check failed"
(
    cd "$PROJECT_ROOT"
    env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PROJECT_ROOT/src" "$VENV/bin/python" - <<'PY'
from pathlib import Path
from tori.config import load_settings
load_settings(Path("tori.toml"), environ={})
import tori
PY
    env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PROJECT_ROOT/src" \
        "$VENV/bin/python" -m tori --help >/dev/null
) || fail "Tori import, configuration, or CLI validation failed"

cat <<'EOF'

Tori core installation complete. Start with ./start-tori.sh from this directory.
Application stores are initialized on first start; the installer creates no user
data, service, credentials or external provider connection. The portable config
contains a generic loopback Ollama example, but no model server/model is installed.
Configure model providers and other external services later in Settings or the
User Guide. Voice Input and Research Worker remain unavailable until separately
provisioned. Planning's Radicale package and MCP Time package are in .venv;
their service/approved tool configuration is a separate owner action.
EOF
