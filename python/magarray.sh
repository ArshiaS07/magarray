#!/usr/bin/env bash
# Runs the tools from the venv python/setup.sh made:  python/magarray.sh view [--file REC] ...
venv="${MAGARRAY_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/magarray/venv}"
[[ -x "$venv/bin/python" ]] || { echo "no venv at $venv: run python/setup.sh first" >&2; exit 1; }
exec "$venv/bin/python" -m magarray "$@"
