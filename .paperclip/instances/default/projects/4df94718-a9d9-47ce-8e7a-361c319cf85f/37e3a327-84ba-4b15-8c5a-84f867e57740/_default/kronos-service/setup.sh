#!/usr/bin/env bash
# Kronos Service Setup
# Adds the Kronos library as a git submodule and installs dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Kronos Service Setup ==="

# 1. Add Kronos as git submodule (vendor/Kronos)
if [ ! -d "vendor/Kronos" ]; then
    echo "Adding Kronos as git submodule..."
    git submodule add https://github.com/shiyu-coder/Kronos.git vendor/Kronos
    git submodule update --init --recursive
else
    echo "Kronos submodule already exists, updating..."
    git submodule update --init --recursive
fi

# 2. Add vendor/Kronos to PYTHONPATH so 'from model import Kronos' works
export PYTHONPATH="${SCRIPT_DIR}/vendor/Kronos:${PYTHONPATH:-}"

# 3. Install Kronos dependencies
echo "Installing Kronos model dependencies..."
pip install -r vendor/Kronos/requirements.txt

# 4. Install kronos-service package
echo "Installing kronos-service..."
pip install -e ".[dev]"

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start the service:"
echo "  export PYTHONPATH=${SCRIPT_DIR}/vendor/Kronos:\$PYTHONPATH"
echo "  python -m kronos_service"
echo ""
echo "Or use the systemd/launchd service file for production."
