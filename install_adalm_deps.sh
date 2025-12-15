#!/usr/bin/env bash
set -euo pipefail

echo "Installing ADALM‑Pluto (ADALM) system dependencies"

if [ -f /etc/debian_version ]; then
  echo "Detected Debian/Ubuntu. Installing apt packages (requires sudo)."
  sudo apt-get update
  # Install common build tools and headers
  sudo apt-get install -y build-essential pkg-config git cmake libxml2-dev libjson-c-dev || true
  # Prefer available libiio package names (libiio0 / libiio-dev) and python bindings if present
  sudo apt-get install -y libiio-dev libiio-utils libiio0 python3-libiio || true
  # AD9361 related packages (optional but useful for Pluto/AD9361 support)
  sudo apt-get install -y libad9361-0 libad9361-dev || true
  echo "Installed apt packages (or attempted best-effort). If some packages were unavailable, consider building libiio from source."
  echo "If you plan to use pyadi-iio from GitHub, consider running after venv activation:"
  echo "  source .venv/bin/activate && pip install git+https://github.com/analogdevicesinc/pyadi-iio.git"
elif [ -f /etc/os-release ] && grep -qi "fedora\|centos\|rhel" /etc/os-release; then
  echo "Detected RHEL/Fedora. Install libiio and related packages using dnf/yum (you may need EPEL)."
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y make gcc gcc-c++ pkgconfig libxml2-devel json-c-devel libiio-devel || true
  else
    sudo yum install -y make gcc gcc-c++ pkgconfig libxml2-devel json-c-devel libiio-devel || true
  fi
  echo "You may need to build libiio from source if packages are missing."
else
  echo "Unknown distro. Please install the following system packages manually: libiio (and headers), libxml2-dev, pkg-config, build-essential, and json-c dev packages."
  echo "See https://github.com/analogdevicesinc/libiio for building libiio from source."
fi

echo "Finished ADALM dependency installation steps."
