#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${1:-/tmp/frontline-eval}"
bootstrap_file="${TMPDIR:-/tmp}/frontline-eval-get-pip.py"

python3 -m venv --without-pip "$venv_dir"
if ! "$venv_dir/bin/python" -m pip --version >/dev/null 2>&1; then
  VENV_DIR="$venv_dir" BOOTSTRAP_FILE="$bootstrap_file" python3 - <<'PY'
import os
import urllib.request

urllib.request.urlretrieve(
    "https://bootstrap.pypa.io/get-pip.py", os.environ["BOOTSTRAP_FILE"]
)
PY
  "$venv_dir/bin/python" "$bootstrap_file"
fi
"$venv_dir/bin/python" -m pip install --require-virtualenv -r "$repo_dir/evals/requirements.txt"
# The shared package's runtime dependencies are all present in the lock above;
# do not let its broad project constraints re-resolve them during setup.
"$venv_dir/bin/python" -m pip install --no-deps -e "$repo_dir/shared"
printf 'Evaluation environment ready: %s\n' "$venv_dir"
