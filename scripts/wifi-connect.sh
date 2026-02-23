#!/bin/bash

SSID="$1"
PASSWORD="$2"
BAND="$3" # "a" for 5GHz, "bg" for 2.4GHz

# Support for explicit hotspot mode
if [ "$1" == "--hotspot" ]; then
    FORCE_HOTSPOT=true
fi

enable_hotspot() {
    echo "Connection failed (or forcing hotspot). Re-enabling hotspot..."
    
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
    HOTSPOT_PASSWORD="touchnstars"

    echo "Creating hotspot: $HOTSPOT_SSID"

    # Create new hotspot with dynamic SSID

    if nmcli device wifi hotspot ifname wlan0 ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASSWORD"; then
        
        
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

if [ "$FORCE_HOTSPOT" = true ]; then
    enable_hotspot
    exit 0
fi

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

# Logic to prefer existing connection if no password provided
if [ -z "$PASSWORD" ] && nmcli connection show "$SSID" >/dev/null 2>&1; then
    echo "Found existing profile for $SSID. Attempting to bring it up..."
    if nmcli connection up "$SSID"; then
        CONNECT_SUCCESS=0
    else
        echo "Failed to bring up existing connection. Retrying with device connect..."
        CONNECT_SUCCESS=1
    fi
else
    CONNECT_SUCCESS=1 # Treat as not yet connected so we fall through to device connect logic if appropriate
fi

# If connection up failed or we have a password (forcing new connection logic)
if [ $CONNECT_SUCCESS -ne 0 ]; then
    # Use array for command construction to handle spaces and quotes safely
    CMD=("nmcli" "device" "wifi" "connect" "$SSID")

    if [ -n "$PASSWORD" ]; then
        CMD=("nmcli" "device" "wifi" "connect" "$SSID" "password" "$PASSWORD" "name" "$SSID")
    fi

    # Execute connection command
    "${CMD[@]}" || CONNECT_SUCCESS=1
fi

if [ $CONNECT_SUCCESS -eq 0 ] && [ -n "$BAND" ]; then
    echo "Applying band preference: $BAND"
    # Use 802-11-wireless.band for better compatibility
    if nmcli connection modify "$SSID" 802-11-wireless.band "$BAND"; then
        echo "Reactivating connection with band preference settings..."
        nmcli connection up "$SSID" || CONNECT_SUCCESS=1
    else
        echo "Warning: Failed to set wifi band to $BAND"
    fi
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

