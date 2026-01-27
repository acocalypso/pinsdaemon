#!/bin/bash
set -e

ACTION=$1
SHARE_PATH="/home/pi/Documents"
SHARE_NAME="Documents"
CONFIG_FILE="/etc/samba/smb.conf"
# Helper markers to identify our block in smb.conf
MARKER_START="# BEGIN PINS_SHARE - Do not edit manually"
MARKER_END="# END PINS_SHARE"

if [[ "$ACTION" == "enable" ]]; then
    echo "Enabling Samba share '$SHARE_NAME' for $SHARE_PATH..."

    # 1. Install Samba
    # Check if smbd is present to verify installation (avoids false positive on 'rc' package state)
    if ! command -v smbd >/dev/null 2>&1; then
        echo "Installing samba..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y samba
    fi

    # 1.5 Ensure user 'pi' exists and has Samba password
    if ! id "pi" >/dev/null 2>&1; then
        echo "Creating system user 'pi'..."
        useradd -m -s /bin/bash pi
        echo "pi:pins" | chpasswd
    fi

    # Check if 'pi' is a samba user
    if ! pdbedit -L -u pi >/dev/null 2>&1; then
        echo "Creating samba user 'pi'..."
        (echo "pins"; echo "pins") | smbpasswd -a -s pi
    fi

    # 2. Ensure directory exists
    if [ ! -d "$SHARE_PATH" ]; then
        echo "Creating directory $SHARE_PATH..."
        mkdir -p "$SHARE_PATH"
        chown pi:pi "$SHARE_PATH" || echo "Warning: Could not set owner"
    fi

    # 2.5 Ensure Global Settings for Guest Access
    # Use the logic from Elektronik Kompendium for a clean baseline if needed, 
    # but specifically enable map to guest = Bad User.
    if [ -f "$CONFIG_FILE" ] && grep -q "\[global\]" "$CONFIG_FILE"; then
        if ! grep -q "map to guest" "$CONFIG_FILE"; then
            sed -i '/\[global\]/a \   map to guest = Bad User' "$CONFIG_FILE"
            echo "Added 'map to guest = Bad User' to global config."
        fi
        # Ensure security is user (default in modern samba, but good to be explicit)
        if ! grep -q "security = user" "$CONFIG_FILE"; then
             sed -i '/\[global\]/a \   security = user' "$CONFIG_FILE"
        fi
    fi

    # 3. Add to smb.conf if not present
    # Ensure config file exists before checking/appending
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Configuration file missing, creating default structure..."
        mkdir -p "$(dirname "$CONFIG_FILE")"
        cat > "$CONFIG_FILE" <<EOF
[global]
   workgroup = WORKGROUP
   security = user
   map to guest = Bad User
   wins support = no
   dns proxy = no

EOF
    fi

    if grep -qF "$MARKER_START" "$CONFIG_FILE"; then
        echo "Configuration block already present in $CONFIG_FILE."
    else
        echo "Appending configuration to $CONFIG_FILE..."
        cat >> "$CONFIG_FILE" <<EOF

$MARKER_START
[$SHARE_NAME]
   comment = PINS Shared Documents
   path = $SHARE_PATH
   browseable = yes
   writeable = yes
   guest ok = yes
   read only = no
   force user = pi
   create mask = 0775
   directory mask = 0775
$MARKER_END
EOF
    fi

    # 4. Restart service
    echo "Restarting Samba services..."
    systemctl unmask smbd nmbd || true
    systemctl enable smbd nmbd || true
    systemctl restart smbd nmbd
    
    echo "Samba Share enabled successfully."
    echo "Windows: \\\\<IP>\\$SHARE_NAME"
    echo "Mac/Linux: smb://<IP>/$SHARE_NAME"

elif [[ "$ACTION" == "disable" ]]; then
    echo "Disabling Samba share..."

    if grep -qF "$MARKER_START" "$CONFIG_FILE"; then
        echo "Removing configuration block from $CONFIG_FILE..."
        # Remove the block between markers (inclusive)
        sed -i "/$MARKER_START/,/$MARKER_END/d" "$CONFIG_FILE"
        
        echo "Reloading Samba services..."
        systemctl reload smbd nmbd
        echo "Samba Share disabled successfully."
    else
        echo "No configuration block found to remove."
    fi

else
    echo "Usage: $0 {enable|disable}"
    exit 1
fi
