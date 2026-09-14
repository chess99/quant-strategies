#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
env_dir=${1:-/srv/quantlab/env}
cache_dir=${2:-/srv/quantlab/cache}
verification_report=${3:-/srv/quantlab/runs/environment-verification.json}
lock_file="${repo_root}/requirements/research-linux-py312.lock"
expected_file="${repo_root}/requirements/research-linux-py312.expected.json"
torch_wheel="${cache_dir}/torch-2.6.0+cpu-cp312-cp312-linux_x86_64.whl"
torch_sha256=59e78aa0c690f70734e42670036d6b541930b8eabbaa18d94e090abf14cc4d91

command -v uv >/dev/null
command -v curl >/dev/null
if [[ -e ${env_dir} ]]; then
  echo "environment directory already exists; use a new empty path: ${env_dir}" >&2
  exit 1
fi

mkdir -p "${cache_dir}" "$(dirname "${verification_report}")"
if [[ ! -f ${torch_wheel} ]]; then
  curl -fL --retry 3 \
    'https://mirrors.aliyun.com/pytorch-wheels/cpu/torch-2.6.0%2Bcpu-cp312-cp312-linux_x86_64.whl' \
    -o "${torch_wheel}"
fi
echo "${torch_sha256}  ${torch_wheel}" | sha256sum --check --status

UV_CACHE_DIR="${cache_dir}/uv" uv python install 3.12.9
UV_CACHE_DIR="${cache_dir}/uv" uv venv --python 3.12.9 "${env_dir}"
UV_CACHE_DIR="${cache_dir}/uv" uv pip sync \
  --python "${env_dir}/bin/python" \
  --find-links "${cache_dir}" \
  --index-url https://mirrors.aliyun.com/pypi/simple/ \
  "${lock_file}"

cd "${repo_root}"
"${env_dir}/bin/python" tools/verify_research_environment.py \
  --expected "${expected_file}" \
  --lock "${lock_file}" \
  --output "${verification_report}"
"${env_dir}/bin/python" -m pytest -q
"${env_dir}/bin/python" tools/validate_repo.py
"${env_dir}/bin/python" -m ruff check src tools tests studies

