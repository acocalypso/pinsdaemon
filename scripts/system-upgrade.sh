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

# Detach the upgrade process to prevent interruption when the service restarts
if [[ "${PINS_UPDATE_DETACHED}" != "true" ]]; then
    echo "Checking for systemd-run to detach process..."
    if command -v systemd-run >/dev/null 2>&1; then
        echo "Detaching upgrade process via systemd-run..."
        # Use systemd-run to start this script in a new transient unit
        # This prevents the script from being killed when sysupdate-api service stops
        systemd-run --unit="pins-sysupgrade-$(date +%s)" \
                    --setenv=PINS_UPDATE_DETACHED=true \
                    --no-block \
                    "$0" "$@"
        
        echo "Upgrade process detached and started in background."
        echo "The system may update and restart the pinsdaemon service shortly."
        exit 0
    else
        echo "Warning: systemd-run not found. Proceeding in foreground."
    fi
fi

# Update package lists
echo "Running apt update..."
export DEBIAN_FRONTEND=noninteractive
apt-get update

# Upgrade packages
echo "Running apt upgrade..."
apt-get upgrade -y

echo "System upgrade completed successfully."
