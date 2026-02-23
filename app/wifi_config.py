import json
import os
from typing import Optional, Dict, Any

# In production this might be /etc/pins/wifi.json or similar
# For now, we'll keep it in the app directory or relative to it.
# Let's say we store it in the same directory as this file for simplicity, 
# but in production it should be somewhere persistent.
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "wifi_config.json")

def load_wifi_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {"auto_connect": False, "ssid": None}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"auto_connect": False, "ssid": None, "band": None}

def save_wifi_config(ssid: Optional[str], auto_connect: bool, band: Optional[str] = None):
    config = {
        "ssid": ssid,
        "auto_connect": auto_connect,
        "band": band
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
