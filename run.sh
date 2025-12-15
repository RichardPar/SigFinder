#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=.venv
if [ -d "${VENV_DIR}" ]; then
  source ${VENV_DIR}/bin/activate
else
  echo "Virtualenv not found. Run ./venv_setup.sh first." >&2
  exit 1
fi

python -m sigfinder "$@"
