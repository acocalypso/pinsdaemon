import asyncio
import uuid
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

class JobStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

@dataclass
class Job:
    id: str
    command: str
    status: JobStatus = JobStatus.STARTED
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    logs: List[str] = field(default_factory=list)
    # Queues for active websocket listeners
    listeners: List[asyncio.Queue] = field(default_factory=list)

    async def add_log(self, line: str):
        self.logs.append(line)
        # Broadcast to all active listeners
        for listener in self.listeners:
            await listener.put(line)

    def register_listener(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.append(q)
        return q

    def remove_listener(self, q: asyncio.Queue):
        if q in self.listeners:
            self.listeners.remove(q)

class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Job] = {}

    async def start_job(self, command: List[str], job_id: Optional[str] = None) -> str:
        if not job_id:
            job_id = str(uuid.uuid4())
        job = Job(id=job_id, command=" ".join(command))
        self.jobs[job_id] = job
        
        # Start background task to run the process
        asyncio.create_task(self._run_process(job_id, command))
        
        return job_id

    async def _monitor_detached_unit(self, job: Job, unit_name: str):
        job.add_log(f"Monitoring detached unit: {unit_name}")
        
        # Start journalctl to follow logs
        journal_cmd = ["sudo", "journalctl", "-f", "-u", unit_name, "--no-tail"]
        journal_proc = await asyncio.create_subprocess_exec(
            *journal_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        async def read_journal():
            while True:
                line = await journal_proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors='replace').strip()
                if decoded:
                    await job.add_log(decoded)

        # Start reading logs in background
        log_task = asyncio.create_task(read_journal())

        # Monitor service status
        final_status = "unknown"
        exit_code = 0
        
        while True:
            await asyncio.sleep(2)
            
            # Check if active
            check_cmd = ["sudo", "systemctl", "is-active", unit_name]
            check_proc = await asyncio.create_subprocess_exec(
                *check_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await check_proc.communicate()
            status = stdout.decode().strip()
            
            if status in ["inactive", "failed"]:
                # Service finished
                final_status = status
                break
        
        # Stop logging
        if journal_proc.returncode is None:
            journal_proc.terminate()
            try:
                await asyncio.wait_for(journal_proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                journal_proc.kill()
        
        await log_task

        # Get detailed exit status
        show_cmd = ["sudo", "systemctl", "show", "-p", "ExecMainStatus,Result", "--value", unit_name]
        try:
            show_proc = await asyncio.create_subprocess_exec(
                *show_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await show_proc.communicate()
        except:
            stdout = b""
            
        # Output like:
        # 0
        # success
        try:
            lines = stdout.decode().strip().splitlines()
            exit_code = int(lines[0]) if lines else 0
            if len(lines) > 1:
                result = lines[1]
            else:
                result = "unknown"
        except:
            exit_code = -1
            result = "error"
            
        job.exit_code = exit_code
        job.finished_at = time.time()
        
        # Check success conditions:
        # 1. Systemd reports success (clean exit 0)
        # 2. Or unit disappeared but we saw "System upgrade completed successfully." in logs
        is_success = (final_status == "inactive" and result == "success" and exit_code == 0)
        
        if not is_success and result == "unknown":
            # Fallback: Check logs for success message
            log_success = any("System upgrade completed successfully." in log for log in job.logs)
            if log_success:
                is_success = True
                job.exit_code = 0 # Assume success
        
        job.status = JobStatus.SUCCESS if is_success else JobStatus.FAILED
        
        for listener in job.listeners:
            await listener.put(None)

    async def _run_process(self, job_id: str, command: List[str]):
        job = self.jobs.get(job_id)
        if not job:
            return

        job.status = JobStatus.RUNNING
        detached_unit = None
        
        try:
            # Create subprocess
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT 
            )

            # Read output line by line
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                # robust decoding used
                decoded_line = line.decode(errors='replace').strip()
                if decoded_line: 
                    await job.add_log(decoded_line)
                    # Check for detachment
                    if "Running as unit:" in decoded_line:
                        # Extract unit name, e.g. "Running as unit: pins-sysupgrade-123.service"
                        parts = decoded_line.split("Running as unit:")
                        if len(parts) > 1:
                            detached_unit = parts[1].strip()

            await process.wait()
            
            # If process exited successfully and we detected a detached unit, switch to monitoring it
            if process.returncode == 0 and detached_unit:
                await self._monitor_detached_unit(job, detached_unit)
                return

            job.exit_code = process.returncode
            job.finished_at = time.time()
            job.status = JobStatus.SUCCESS if job.exit_code == 0 else JobStatus.FAILED
            
            # Notify listeners that job is done
            for listener in job.listeners:
                await listener.put(None)

        except Exception as e:
            import traceback
            error_msg = f"Internal Error: {repr(e)}"
            print(f"Job failed with exception: {traceback.format_exc()}") # Print to server console for debugging
            await job.add_log(error_msg)
            
            job.exit_code = -1
            job.status = JobStatus.FAILED
            job.finished_at = time.time()
            for listener in job.listeners:
                await listener.put(None)

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

# Global instance
job_manager = JobManager()
