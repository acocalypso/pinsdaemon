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

    async def start_job(self, command: List[str]) -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, command=" ".join(command))
        self.jobs[job_id] = job
        
        # Start background task to run the process
        asyncio.create_task(self._run_process(job_id, command))
        
        return job_id

    async def _run_process(self, job_id: str, command: List[str]):
        job = self.jobs.get(job_id)
        if not job:
            return

        job.status = JobStatus.RUNNING
        
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

            await process.wait()
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
