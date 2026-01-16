# System Upgrade API Daemon

A minimal Python-based daemon that exposes a secured HTTP endpoint to trigger system updates (`apt update && apt upgrade`) and stream the logs via WebSockets.

## Features

- **Platform Agnostic**: Runs on ARM64 (Raspberry Pi/Jetson) and x86_64.
- **Secure**:
  - Runs as a dedicated restricted user.
  - Hard-coded command execution (no arbitrary shell).
  - Uses `sudoers` for fine-grained privilege delegation.
  - Bearer token authentication.
- **Real-time Feedback**: WebSocket endpoint streams standard output and error of the update command.

## Installation

### 1. Prerequisites

- Python 3.9+ installed.
- `pip` and `venv` available (usually `apt install python3-venv`).

### 2. User Setup

Create a dedicated user for the service:

```bash
sudo useradd -r -s /bin/false sysupdate-api
```

### 3. Deploy Code

Clone this repository or copy files to `/opt/pinsdeamon` (or your preferred location).

```bash
sudo mkdir -p /opt/pinsdeamon
sudo cp -r . /opt/pinsdeamon/
sudo chown -R sysupdate-api:sysupdate-api /opt/pinsdeamon
```

### 4. Install Dependencies

Switch to the service user (or install system-wide if preferred, but venv is recommended):

```bash
cd /opt/pinsdeamon
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Setup the Upgrade Script

Copy the upgrade script to a secure location and make it executable:

```bash
sudo cp scripts/system-upgrade.sh /usr/local/bin/system-upgrade.sh
sudo chmod +x /usr/local/bin/system-upgrade.sh
```

### 6. Configure Sudoers

Allow the `sysupdate-api` user to run **only** this specific script as root without a password.

Create `/etc/sudoers.d/sysupdate-api`:

```bash
sysupdate-api ALL=(root) NOPASSWD: /usr/local/bin/system-upgrade.sh
```

Ensure correct permissions:

```bash
sudo chmod 440 /etc/sudoers.d/sysupdate-api
```

### 7. Setup Systemd Service

Edit `systemd/sysupdate-api.service` to match your paths and set a secure `API_TOKEN`.

Then install the service:

```bash
sudo cp systemd/sysupdate-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sysupdate-api
sudo systemctl start sysupdate-api
```

## Usage

### Trigger Update

**POST** `/upgrade`
Headers: `Authorization: Bearer <your-token>`
Body: `{"dryRun": false}`

Response:
```json
{
  "jobId": "e3b0c442-...",
  "status": "started",
  ...
}
```

### Check Status

**GET** `/jobs/{jobId}`
Headers: `Authorization: Bearer <your-token>`

### Stream Logs

**WebSocket** `/logs/{jobId}?token=<your-token>`

Connect via a WebSocket client. You will receive existing logs immediately, followed by live updates until the process exits.
