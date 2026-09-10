#!/usr/bin/env sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$script_dir/scenelight_sdk.py" ]; then
    launcher="$script_dir/scenelight_sdk.py"
else
    launcher="$script_dir/_scenelight/scenelight_sdk.py"
fi
exec python3 "$launcher" "$@"
