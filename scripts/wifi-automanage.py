#!/usr/bin/env python3
import json
import subprocess
import sys
import os
import time

# Configuration paths
# Assuming this script is in /usr/local/bin or similar in production,
# but for now we look for config relative to the app structure or in /etc/pins
CONFIG_PATHS = [
    "/opt/pinsdaemon/app/wifi_config.json",
    "/etc/pins/wifi_config.json",
    os.path.join(os.path.dirname(__file__), "../app/wifi_config.json"), # For development
    "wifi_config.json"
]

WIFI_CONNECT_SCRIPT = os.path.join(os.path.dirname(__file__), "wifi-connect.sh")

def load_config():
    for path in CONFIG_PATHS:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config from {path}: {e}")
    return None

def scan_networks(ssid):
    try:
        # Force a scan
        subprocess.run(["nmcli", "device", "wifi", "rescan"], check=False)
        time.sleep(3)
        
        # List networks
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        available_ssids = result.stdout.strip().split('\n')
        return ssid in available_ssids
    except subprocess.CalledProcessError as e:
        print(f"Error scanning networks: {e}")
        return False

def connect_to_wifi(ssid, band=None):
    print(f"Attempting to connect to {ssid} (Band: {band})...")
    try:
        # Check if we have a connection profile for this SSID
        # Or call wifi-connect.sh script to enforce band?
        # The internal logic of wifi-connect.sh tries to connect and falls back to hotspot.
        # It's better to use wifi-connect.sh here too if we want band enforcement,
        # because 'nmcli connection up id <SSID>' assumes the profile is already correct.
        
        # If band is set, we need to ensure the profile respects it.
        # But we don't have the password here.
        # If we use wifi-connect.sh without password, does it work for existing profiles?
        # Yes, if no password provided, it uses `nmcli device wifi connect "$SSID" || ...`
        
        # So we can pass the band to wifi-connect.sh
        
        args = ["sudo", WIFI_CONNECT_SCRIPT, ssid, "", band if band else ""]
        
        # Do not filter empty args as positional arguments matter for wifi-connect.sh
        # args = [a for a in args if a]
        
        result = subprocess.run(args)
        return result.returncode == 0
            
    except Exception as e:
        print(f"Exception during connection: {e}")
        return False

def start_hotspot():
    print("Starting hotspot...")
    try:
        subprocess.run([WIFI_CONNECT_SCRIPT, "--hotspot"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to start hotspot: {e}")
        sys.exit(1)

def main():
    config = load_config()
    
    if not config:
        print("No wifi configuration found.")
        start_hotspot()
        return

    ssid = config.get("ssid")
    auto_connect = config.get("auto_connect", False)
    band = config.get("band", None) # "bg" or "a"

    if auto_connect and ssid:
        print(f"Auto-connect enabled for SSID: {ssid}")
        if scan_networks(ssid):
            print(f"Network {ssid} found.")
            if connect_to_wifi(ssid, band):
                 sys.exit(0)
            else:
                 print("Connection failed.")
        else:
            print(f"Network {ssid} not found in scan results.")
    else:
        print("Auto-connect disabled or SSID not configured.")

    # Fallback to hotspot
    start_hotspot()

if __name__ == "__main__":
    main()
