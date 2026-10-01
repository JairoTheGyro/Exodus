#!/usr/bin/env bash
# Codex cloud setup: install focused test dependencies, never production data.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
cloud_venv="${EXODUS_CLOUD_VENV:-${repo_dir}/.venv}"

"${python_bin}" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
if ! command -v node >/dev/null 2>&1; then
    echo 'Node.js is required for UI checks. Select Node 22 or newer in the development environment.' >&2
    exit 1
fi
node -e 'if (Number(process.versions.node.split(".")[0]) < 22 || typeof CustomEvent !== "function") { console.error("Use Node 22 or newer for the UI checks."); process.exit(1); }'

"${python_bin}" -m venv "${cloud_venv}"
"${cloud_venv}/bin/python" -m pip install --disable-pip-version-check -r "${repo_dir}/requirements-cloud-test.txt"

printf '\nFocused dependencies installed. No app services were started.\n'
printf 'Run: %q %q\n' "${cloud_venv}/bin/python" "${repo_dir}/scripts/cloud_test.py"
