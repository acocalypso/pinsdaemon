#!/bin/bash
# set -e is removed to handle errors manually

SSID="$1"
PASSWORD="$2"

enable_hotspot() {
    echo "Connection failed. Re-enabling hotspot..."
    
    # Get CPU ID for unique SSID
    CPU_ID="0000"
    if [ -f /proc/cpuinfo ]; then
        # Use user provided logic to extract serial
        CPU_ID=$(grep Serial /proc/cpuinfo | awk '{print substr($3, length($3)-4)}')
    fi
    
    # Fallback if empty
    if [ -z "$CPU_ID" ]; then
        CPU_ID="0000"
    fi

    HOTSPOT_SSID="pins-$CPU_ID"
    HOTSPOT_PASSWORD="touchnstars"  # Change this

    echo "Creating hotspot: $HOTSPOT_SSID"

    # Create new hotspot with dynamic SSID
    # Note: We rely on nmcli creating a connection. We try to infer the name or just modify common names.
    if nmcli device wifi hotspot ifname wlan0 ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASSWORD"; then
        
        # Disable Wi-Fi powersave on this hotspot profile
        # Use the name 'hotspot-ap' if user script assumes it, or try to find the active connection
        # The user's script deleted 'hotspot-ap' before creating. 
        # nmcli usually creates 'Hotspot' or similar if name not specified. 
        # But let's try to target what was just active/created.
        
        # Try finding the connection we just created (active on wlan0)
        NEW_CONN=$(nmcli -t -f NAME,DEVICE connection show --active | grep ":wlan0" | cut -d: -f1 | head -n1)
        
        if [ -n "$NEW_CONN" ]; then
             echo "Configuring powersave for $NEW_CONN"
             nmcli connection modify "$NEW_CONN" 802-11-wireless.powersave 2 || true
        else
             # Fallback to hardcoded names just in case
             nmcli connection modify hotspot-ap 802-11-wireless.powersave 2 2>/dev/null || true
        fi

        # Extra safeguard: also disable kernel powersave flag for this device
        if command -v iw >/dev/null 2>&1; then
            iw dev wlan0 set power_save off || true
        fi
        
        echo "Hotspot enabled successfully."
    else
        echo "Failed to enable hotspot."
    fi
}

if [ -z "$SSID" ]; then
    echo "Error: SSID is required."
    exit 1
fi

echo "Preparing to connect to $SSID..."

# 0. Force a rescan to ensure we know the security type
# We run this in the background/wait briefly or just run it. 
# Sometimes rescan fails if busy, we ignore error.
sudo nmcli device wifi rescan 2>/dev/null || true
# Give it a moment to populate
sleep 3

# 1. Remove existing hotspot connection if any
# Find any connections named "hotspot-ap" or starting with "Hotspot" (default nmcli naming)
echo "Cleaning up existing hotspot connections..."
existing_hotspots=$(nmcli -t -f NAME connection show | grep -E "^(Hotspot|hotspot-ap)")

if [ -n "$existing_hotspots" ]; then
    # Process each line to handle potential spaces in names
    while IFS= read -r conn; do
        if [ -n "$conn" ]; then
            echo "Removing hotspot connection: $conn"
            nmcli connection delete "$conn" || true
        fi
    done <<< "$existing_hotspots"
fi

# 2. Clean up any EXISTING profiles for the target SSID
# If we have a new password, remove old connection to force update.
# If no password is provided, we keep existing profile (if any) to reuse saved credentials.
if [ -n "$PASSWORD" ]; then
    if nmcli connection show "$SSID" >/dev/null 2>&1; then
        echo "Removing stale connection profile for $SSID..."
        nmcli connection delete "$SSID" || true
    fi
fi

# 3. Connect to the new wifi network
echo "Connecting to $SSID..."

CONNECT_SUCCESS=0
if [ -n "$PASSWORD" ]; then
    # Use explicit connection name to prevent duplicates and ensure settings apply to the right profile
    nmcli device wifi connect "$SSID" password "$PASSWORD" name "$SSID" || CONNECT_SUCCESS=1
else
    # If no password provided, try connecting. This works for Open networks or using existing saved profiles.
    nmcli device wifi connect "$SSID" || CONNECT_SUCCESS=1
fi

if [ $CONNECT_SUCCESS -ne 0 ]; then
    echo "Failed to connect to $SSID."
    enable_hotspot
    exit 1
fi

echo "Successfully connected to $SSID."
# Optional: Disable powersave on client connection too
# Filter specifically for wireless connections to avoid configuring ethernet connections
CURRENT_CONN=$(nmcli -t -f NAME,TYPE connection show --active | grep ":802-11-wireless" | cut -d: -f1 | head -n1)
if [ -n "$CURRENT_CONN" ]; then
    nmcli connection modify "$CURRENT_CONN" 802-11-wireless.powersave 2 || true
fi
exit 0

