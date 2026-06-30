#!/bin/bash
# ============================================================================
# deploy_server.sh — Deploy server_inference.py to the FoundationPose Docker
# ============================================================================
#
# This script:
#   1. Copies server_inference.py to the remote server via scp
#   2. Copies it into the running 'foundationpose' Docker container
#   3. Installs required Python packages (msgpack, zmq) inside the container
#
# Usage:
#   bash deploy_server.sh
#
# Prerequisites:
#   - sshpass installed (sudo apt install sshpass), OR enter password manually
#   - Remote server reachable at 10.72.18.159
#   - Docker container 'foundationpose' running on the remote server
# ============================================================================

set -e

SERVER_USER="manthan"
SERVER_IP="10.72.18.159"
SERVER_PASS="REDACTED"
CONTAINER="foundationpose"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="${SCRIPT_DIR}/server_inference.py"

echo "═══════════════════════════════════════════════════════════════"
echo "  FoundationPose Server Deployment"
echo "═══════════════════════════════════════════════════════════════"

if [ ! -f "$SERVER_SCRIPT" ]; then
    echo "ERROR: server_inference.py not found at ${SERVER_SCRIPT}"
    exit 1
fi

echo ""
echo "[1/3] Copying server_inference.py to remote server..."
echo "      → ${SERVER_USER}@${SERVER_IP}:/tmp/server_inference.py"
scp "$SERVER_SCRIPT" "${SERVER_USER}@${SERVER_IP}:/tmp/server_inference.py"

echo ""
echo "[2/3] Copying into Docker container '${CONTAINER}'..."
ssh "${SERVER_USER}@${SERVER_IP}" \
    "docker cp /tmp/server_inference.py ${CONTAINER}:/workspace/server_inference.py"

echo ""
echo "[3/3] Installing Python dependencies inside container..."
ssh "${SERVER_USER}@${SERVER_IP}" \
    "docker exec ${CONTAINER} pip install pyzmq msgpack msgpack-numpy"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Deployment complete!"
echo ""
echo "  To start the server, run:"
echo "    ssh ${SERVER_USER}@${SERVER_IP}"
echo "    docker exec -it ${CONTAINER} python3 /workspace/server_inference.py"
echo "═══════════════════════════════════════════════════════════════"
