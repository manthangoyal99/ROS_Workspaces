#!/bin/bash
# Script to download the YCB Apple mesh into the FoundationPose Docker container
# This script will prompt you for the SSH password for manthan@10.72.18.159

SERVER_USER="manthan"
SERVER_IP="10.72.18.159"
CONTAINER="foundationpose"

echo "Connecting to the GPU Server to download the Apple mesh..."
echo "Please enter the password for ${SERVER_USER}@${SERVER_IP} when prompted."

ssh "${SERVER_USER}@${SERVER_IP}" << 'EOF'
    docker exec -i foundationpose /bin/bash -c "
        echo 'Creating directory...'
        mkdir -p /workspace/demo_data/apple/mesh
        cd /workspace/demo_data/apple/mesh
        
        echo 'Downloading YCB 013_apple...'
        wget -q --show-progress http://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/data/google/013_apple_google_16k.tgz
        
        echo 'Extracting and renaming files...'
        tar -xzf 013_apple_google_16k.tgz
        mv 013_apple/google_16k/textured.obj textured_simple.obj
        mv 013_apple/google_16k/textured.mtl textured_simple.mtl
        mv 013_apple/google_16k/texture_map.png texture_map.png
        
        echo 'Cleaning up...'
        rm -rf 013_apple 013_apple_google_16k.tgz
        echo 'Done! The apple mesh is ready.'
    "
EOF
