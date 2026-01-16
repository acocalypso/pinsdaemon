#!/usr/bin/env bash
set -e

echo "Starting system upgrade..."

# Optional: Handle dry-run argument
if [[ "$1" == "--dry-run" ]]; then
    echo "Dry run mode active. No changes will be made."
    echo "Files needed to be upgraded would be listed here."
    # Simulate work
    sleep 2
    echo "Done (Dry Run)."
    exit 0
fi

# Update package lists
echo "Running apt update..."
export DEBIAN_FRONTEND=noninteractive
apt-get update

# Upgrade packages
echo "Running apt upgrade..."
apt-get upgrade -y

echo "System upgrade completed successfully."
