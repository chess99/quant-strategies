#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $# -eq 0 ]]; then
  exec uv run --no-project --python 3.12.9 "${repo_root}/tools/rebuild_research_env.py"
fi
args=()
[[ $# -lt 1 ]] || args+=(--env-dir "$1")
[[ $# -lt 2 ]] || args+=(--cache-dir "$2")
[[ $# -lt 3 ]] || args+=(--output "$3")
exec uv run --no-project --python 3.12.9 "${repo_root}/tools/rebuild_research_env.py" "${args[@]}"
