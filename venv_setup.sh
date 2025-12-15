#!/usr/bin/env bash
set -euo pipefail

PY=python3
VENV_DIR=.venv

INSTALL_ADALM=0
if [ "${1-}" = "--adalm" ] || [ "${1-}" = "-a" ]; then
	INSTALL_ADALM=1
fi

echo "Creating venv in ${VENV_DIR} using ${PY}..."
$PY -m venv ${VENV_DIR}
echo "Activating venv and installing requirements..."
source ${VENV_DIR}/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [ "$INSTALL_ADALM" -eq 1 ]; then
	echo "Installing ADALM (system) dependencies..."
	./install_adalm_deps.sh || echo "install_adalm_deps.sh failed; see README for manual steps."
fi

echo "Done. Activate with: source ${VENV_DIR}/bin/activate"
