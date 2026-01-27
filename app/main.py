import os
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

class UpgradeRequest(BaseModel):
    dryRun: bool = False

class SambaRequest(BaseModel):
    enable: bool

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
