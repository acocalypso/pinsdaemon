import os
import json
import asyncio
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from .auth import verify_token
from .job_manager import job_manager, JobStatus

app = FastAPI(title="System Update Daemon")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
# On Windows dev environment, we might want to mock the command.
# In production content, this will be the real path.
# SCRIPT_PATH = os.getenv("UPDATE_SCRIPT_PATH", "/usr/local/bin/system-upgrade.sh")
SCRIPT_PATH = os.getenv("UPDATE_SCRIPT_PATH", "/usr/local/bin/system-upgrade.sh")
SAMBA_SCRIPT_PATH = os.getenv("SAMBA_SCRIPT_PATH", "/usr/local/bin/manage-samba.sh")

# Determine default path for wifi-scan.py
# In production, it's /usr/local/bin/wifi-scan.py
# In dev (Windows/local), it might be relative.
DEFAULT_WIFI_SCAN = "/usr/local/bin/wifi-scan.py"
if not os.path.exists(DEFAULT_WIFI_SCAN):
    DEFAULT_WIFI_SCAN = os.path.join(os.path.dirname(__file__), "../scripts/wifi-scan.py")

WIFI_SCAN_SCRIPT_PATH = os.getenv("WIFI_SCAN_SCRIPT_PATH", DEFAULT_WIFI_SCAN)
WIFI_CONNECT_SCRIPT_PATH = os.getenv("WIFI_CONNECT_SCRIPT_PATH", "/usr/local/bin/wifi-connect.sh")


class UpgradeRequest(BaseModel):
    dryRun: bool = False

class SambaRequest(BaseModel):
    enable: bool

class WifiNetwork(BaseModel):
    mac: Optional[str] = None
    ssid: Optional[str] = None
    signal_strength: Optional[int] = None
    quality: Optional[str] = None
    encrypted: bool = False
    channel: Optional[int] = None
    frequency: Optional[float] = None

class WifiConnectRequest(BaseModel):
    ssid: str
    password: Optional[str] = None

class JobResponse(BaseModel):

    jobId: str
    status: JobStatus
    exitCode: Optional[int]
    startedAt: float
    finishedAt: Optional[float]
    command: str

@app.post("/upgrade", response_model=JobResponse, dependencies=[Depends(verify_token)])
async def trigger_upgrade(request: UpgradeRequest):
    """
    Triggers the system upgrade script.
    """
    # Construct command
    # Using 'sudo' + script path.
    # Note: verify sudoers is set up correctly.
    cmd = ["sudo", "-n", SCRIPT_PATH]
    if request.dryRun:
        # Pass a flag if the script supports it, or just log meant for dry run.
        # Assuming the script takes --dry-run
        cmd.append("--dry-run")

    job_id = await job_manager.start_job(cmd)
    job = job_manager.get_job(job_id)
    
    return JobResponse(
        jobId=job.id,
        status=job.status,
        exitCode=job.exit_code,
        startedAt=job.created_at,
        finishedAt=job.finished_at,
        command=job.command
    )

@app.post("/samba", response_model=JobResponse, dependencies=[Depends(verify_token)])
async def trigger_samba(request: SambaRequest):
    """
    Enable or Disable Samba (SMB) Share.
    """
    action = "enable" if request.enable else "disable"
    cmd = ["sudo", "-n", SAMBA_SCRIPT_PATH, action]
    
    job_id = await job_manager.start_job(cmd)
    job = job_manager.get_job(job_id)
    
    return JobResponse(
        jobId=job.id,
        status=job.status,
        exitCode=job.exit_code,
        startedAt=job.created_at,
        finishedAt=job.finished_at,
        command=job.command
    )

@app.get("/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(verify_token)])
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobResponse(
        jobId=job.id,
        status=job.status,
        exitCode=job.exit_code,
        startedAt=job.created_at,
        finishedAt=job.finished_at,
        command=job.command
    )

@app.websocket("/logs/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: str):
    # Note: WebSocket cannot use the standard HTTPBearer dependency easily 
    # because headers are handled differently in WS handshake or not supported by some clients in standard ways.
    # Often tokens are passed in query param for WS: ?token=...
    # For simplicity here, we'll check query param.
    
    token = websocket.query_params.get("token")
    if token != os.getenv("API_TOKEN", "change-me-please"):
        await websocket.close(code=1008) # Policy Violation
        return

    job = job_manager.get_job(job_id)
    if not job:
        await websocket.close(code=1000, reason="Job not found")
        return

    await websocket.accept()

    # 1. Send past logs
    for line in job.logs:
        await websocket.send_text(line)

    # 2. If job is finished, close
    if job.finished_at is not None:
        await websocket.close()
        return

    # 3. Listen for live logs
    listener_queue = job.register_listener()
    try:
        while True:
            line = await listener_queue.get()
            if line is None:
                # End of stream signal
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        # Client disconnected
        pass
    finally:
        job.remove_listener(listener_queue)
        # Only close if not already closed
        try:
            await websocket.close()
        except:
            pass

@app.get("/wifi/scan", response_model=List[WifiNetwork], dependencies=[Depends(verify_token)])
async def scan_wifi():
    """
    Scans for available WiFi networks.
    """
    if not os.path.exists(WIFI_SCAN_SCRIPT_PATH):
         raise HTTPException(status_code=500, detail=f"WiFi scan script not found at {WIFI_SCAN_SCRIPT_PATH}")

    try:
        # Run the python script
        cmd = ["python3", WIFI_SCAN_SCRIPT_PATH]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error_details = stderr.decode()
            print(f"WiFi scan error: {error_details}")
            # Try to return partial results or empty list? 
            # Or raise error. Let's raise error for now.
            raise Exception(f"Script failed with code {proc.returncode}: {error_details}")
            
        output = stdout.decode().strip()
        if not output:
             return []
        return json.loads(output)
        
    except Exception as e:
        import traceback
        traceback.print_exc() # Print full stack trace to logs
        print(f"WiFi scan failed: {e}")
        # Return 500
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/wifi/connect", response_model=JobResponse, dependencies=[Depends(verify_token)])
async def connect_wifi(request: WifiConnectRequest):
    """
    Connects to a WiFi network.
    This starts a background job to run the connection script.
    """
    cmd = ["sudo", "-n", WIFI_CONNECT_SCRIPT_PATH, request.ssid, request.password or ""]
    
    # Check if script exists (only nice to have check, the job will fail if not found)
    # But locally on windows it's different path.
    
    job_id = await job_manager.start_job(cmd)
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not created")
        
    return JobResponse(
        jobId=job.id,
        status=job.status,
        exitCode=job.exit_code,
        startedAt=job.created_at,
        finishedAt=job.finished_at,
        command=job.command.replace(request.password or "PASSWORD", "***") if request.password else job.command
    )


