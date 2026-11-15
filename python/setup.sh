#!/usr/bin/env bash
# The Python environment for the tools; safe to re-run.
#   python/setup.sh   then   python/magarray.sh view
# The repository sits on exFAT, which cannot hold symlinks, and a venv needs them, so the
# venv lives outside it in $MAGARRAY_VENV (default ~/.local/share/magarray/venv).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is missing: https://docs.astral.sh/uv/" >&2; exit 1; }
export UV_PROJECT_ENVIRONMENT="${MAGARRAY_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/magarray/venv}"
uv sync --extra viewer
if ! id -nG | tr ' ' '\n' | grep -qx dialout; then
    echo "note: you are not in group 'dialout', so serial ports will not open:" >&2
    echo "      sudo usermod -aG dialout \"$USER\", then log in again" >&2
fi
echo "venv: $UV_PROJECT_ENVIRONMENT"
