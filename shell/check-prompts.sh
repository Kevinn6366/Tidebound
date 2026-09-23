#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -x "$root/.venv/bin/python" ]; then
    exec "$root/.venv/bin/python" "$root/scripts/check_prompts.py" "$@"
fi
exec python3 "$root/scripts/check_prompts.py" "$@"
