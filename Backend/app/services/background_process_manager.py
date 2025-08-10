import asyncio
import time
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timedelta
from enum import Enum
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessType(Enum):
    """Types of background processes"""
    ADMIN_QUOTA_REFRESH = "admin_quota_refresh"
    ADMIN_STORAGE_CLEANUP = "admin_storage_cleanup"
    ADMIN_BACKUP_OPERATION = "admin_backup_operation"
    USER_FILE_UPLOAD = "user_file_upload"
    USER_FILE_DOWNLOAD = "user_file_download"
    USER_BATCH_OPERATION = "user_batch_operation"

class ProcessPriority(Enum):
    """Process priority levels"""
    CRITICAL = 1    # Admin operations that must complete immediately
    HIGH = 2        # Admin operations with high priority
    NORMAL = 3      # Regular user operations
    LOW = 4         # Background maintenance tasks

class ProcessStatus(Enum):
    """Process status states"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class BackgroundProcess:
    """Represents a background process with tracking information"""
    
    def __init__(
        self,
        process_id: str,
        process_type: ProcessType,
        priority: ProcessPriority,
        description: str,
        admin_initiated: bool = False
    ):
        self.process_id = process_id
        self.process_type = process_type
        self.priority = priority
        self.description = description
        self.admin_initiated = admin_initiated
        self.status = ProcessStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.progress = 0.0  # 0.0 to 100.0
        self.error_message: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self.metadata: Dict[str, Any] = {}
    
    def start(self):
        """Mark process as started"""
        self.status = ProcessStatus.RUNNING
        self.started_at = datetime.now()
        logger.info(f"Process {self.process_id} started: {self.description}")
    
    def update_progress(self, progress: float):
        """Update process progress (0.0 to 100.0)"""
        self.progress = max(0.0, min(100.0, progress))
        if self.progress % 10 == 0:  # Log every 10% progress
            logger.info(f"Process {self.process_id} progress: {self.progress:.1f}%")
    
    def complete(self, result: Optional[Dict[str, Any]] = None):
        """Mark process as completed"""
        self.status = ProcessStatus.COMPLETED
        self.completed_at = datetime.now()
        self.progress = 100.0
        self.result = result
        logger.info(f"Process {self.process_id} completed: {self.description}")
    
    def fail(self, error_message: str):
        """Mark process as failed"""
        self.status = ProcessStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error_message
        logger.error(f"Process {self.process_id} failed: {error_message}")
    
    def cancel(self):
        """Mark process as cancelled"""
        self.status = ProcessStatus.CANCELLED
        self.completed_at = datetime.now()
        logger.info(f"Process {self.process_id} cancelled: {self.description}")
    
    def get_duration(self) -> Optional[timedelta]:
        """Get process duration if completed"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert process to dictionary for API responses"""
        return {
            "process_id": self.process_id,
            "process_type": self.process_type.value,
            "priority": self.priority.value,
            "description": self.description,
            "admin_initiated": self.admin_initiated,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "error_message": self.error_message,
            "result": self.result,
            "metadata": self.metadata,
            "duration_seconds": self.get_duration().total_seconds() if self.get_duration() else None
        }

class BackgroundProcessManager:
    """Manages background processes with priority-based queuing"""
    
    def __init__(self):
        self.processes = {}  # Store active processes
        self.admin_queue = asyncio.PriorityQueue()  # Priority queue for admin processes
        self.user_queue = asyncio.PriorityQueue()   # Priority queue for user processes
        self.admin_workers = 2  # Number of admin workers
        self.user_workers = 3   # Number of user workers
        self.running = False
        self._workers_started = False  # Track if workers have been started
        # Don't start workers during import - start them lazily when needed
    
    def _ensure_workers_started(self):
        """Ensure workers are started (lazy initialization)"""
        if not self._workers_started and not self.running:
            self._start_workers()
    
    def _start_workers(self):
        """Start background worker tasks"""
        if self._workers_started:
            return
            
        self.running = True
        self._workers_started = True
        
        # Start workers in a new event loop if none exists
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, start workers normally
            for i in range(self.admin_workers):
                asyncio.create_task(self._admin_worker(f"admin_worker_{i}"))
            
            for i in range(self.user_workers):
                asyncio.create_task(self._user_worker(f"user_worker_{i}"))
                
        except RuntimeError:
            # No running loop, workers will be started when first async method is called
            logger.info("No running event loop, workers will start when needed")
            return
        
        logger.info(f"Started {self.admin_workers} admin workers and {self.user_workers} user workers")
    
    async def _admin_worker(self, worker_name: str):
        """Admin worker - processes high-priority admin operations first"""
        while self.running:
            try:
                if not self.admin_queue.empty():
                    # Get highest priority admin process
                    priority, process = await self.admin_queue.get()
                    await self._execute_process(process, worker_name)
                else:
                    # If no admin processes, help with user processes
                    if not self.user_queue.empty():
                        priority, process = await self.user_queue.get()
                        await self._execute_process(process, worker_name)
                    else:
                        await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Admin worker {worker_name} error: {e}")
                await asyncio.sleep(1)
    
    async def _user_worker(self, worker_name: str):
        """User worker - processes normal priority user operations"""
        while self.running:
            try:
                if not self.user_queue.empty():
                    priority, process = await self.user_queue.get()
                    await self._execute_process(process, worker_name)
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"User worker {worker_name} error: {e}")
                await asyncio.sleep(1)
    
    async def _execute_process(self, process: BackgroundProcess, worker_name: str):
        """Execute a background process"""
        try:
            logger.info(f"Worker {worker_name} executing process {process.process_id}: {process.description}")
            process.start()
            
            # Execute the actual process logic
            # This is a placeholder - in real implementation, you'd call the actual process function
            await self._simulate_process_execution(process)
            
            if process.status == ProcessStatus.RUNNING:
                process.complete({"worker": worker_name, "execution_time": time.time()})
                
        except Exception as e:
            logger.error(f"Error executing process {process.process_id}: {e}")
            process.fail(str(e))
        finally:
            # Clean up completed processes after some time
            if process.status in [ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.CANCELLED]:
                # Keep process info for 1 hour for monitoring
                await asyncio.sleep(3600)
                if process.process_id in self.processes:
                    del self.processes[process.process_id]
    
    async def _simulate_process_execution(self, process: BackgroundProcess):
        """Simulate process execution for testing purposes"""
        # Simulate different process types
        if process.process_type == ProcessType.ADMIN_QUOTA_REFRESH:
            await self._simulate_quota_refresh(process)
        elif process.process_type == ProcessType.USER_FILE_UPLOAD:
            await self._simulate_file_upload(process)
        else:
            # Generic process simulation
            for i in range(10):
                await asyncio.sleep(0.1)
                process.update_progress((i + 1) * 10)
    
    async def _simulate_quota_refresh(self, process: BackgroundProcess):
        """Simulate quota refresh process"""
        steps = ["Connecting to Google Drive", "Fetching account info", "Updating quota data", "Saving to database"]
        for i, step in enumerate(steps):
            await asyncio.sleep(0.2)
            process.update_progress((i + 1) * 25)
            process.metadata["current_step"] = step
    
    async def _simulate_file_upload(self, process: BackgroundProcess):
        """Simulate file upload process"""
        steps = ["Preparing file", "Uploading chunks", "Verifying upload", "Updating metadata"]
        for i, step in enumerate(steps):
            await asyncio.sleep(0.3)
            process.update_progress((i + 1) * 25)
            process.metadata["current_step"] = step
    
    def add_process(
        self,
        process_type: ProcessType,
        priority: ProcessPriority,
        description: str,
        admin_initiated: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a new background process to the appropriate queue"""
        # Ensure workers are started when adding first process
        self._ensure_workers_started()
        
        process_id = str(uuid.uuid4())
        process = BackgroundProcess(
            process_id=process_id,
            process_type=process_type,
            priority=priority,
            description=description,
            admin_initiated=admin_initiated
        )
        
        if metadata:
            process.metadata.update(metadata)
        
        # Store the process
        self.processes[process_id] = process
        
        # Add to appropriate queue based on priority and type
        if admin_initiated or priority in [ProcessPriority.CRITICAL, ProcessPriority.HIGH]:
            # Admin processes go to admin queue
            self.admin_queue.put_nowait((priority.value, process))
            logger.info(f"Added admin process {process_id} to admin queue with priority {priority.name}")
        else:
            # User processes go to user queue
            self.user_queue.put_nowait((priority.value, process))
            logger.info(f"Added user process {process_id} to user queue with priority {priority.name}")
        
        return process_id
    
    def get_process(self, process_id: str) -> Optional[BackgroundProcess]:
        """Get a specific process by ID"""
        return self.processes.get(process_id)
    
    def get_all_processes(self, admin_only: bool = False) -> list[BackgroundProcess]:
        """Get all processes, optionally filtered by admin status"""
        if admin_only:
            return [p for p in self.processes.values() if p.admin_initiated]
        return list(self.processes.values())
    
    def get_active_processes(self, admin_only: bool = False) -> list[BackgroundProcess]:
        """Get currently active processes"""
        active = [p for p in self.processes.values() if p.status == ProcessStatus.RUNNING]
        if admin_only:
            return [p for p in active if p.admin_initiated]
        return active
    
    def cancel_process(self, process_id: str) -> bool:
        """Cancel a running process"""
        process = self.processes.get(process_id)
        if process and process.status == ProcessStatus.RUNNING:
            process.cancel()
            logger.info(f"Process {process_id} cancelled")
            return True
        return False
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue and process status"""
        return {
            "admin_queue_size": self.admin_queue.qsize(),
            "user_queue_size": self.user_queue.qsize(),
            "total_processes": len(self.processes),
            "active_processes": len(self.get_active_processes()),
            "admin_processes": len(self.get_active_processes(admin_only=True)),
            "user_processes": len(self.get_active_processes(admin_only=False)),
            "admin_workers": self.admin_workers,
            "user_workers": self.user_workers,
            "running": self.running
        }
    
    def stop(self):
        """Stop the background process manager"""
        self.running = False
        logger.info("Background process manager stopped")

# Global background process manager instance
background_process_manager = BackgroundProcessManager()

# Export the manager for use in other parts of the application
__all__ = [
    "BackgroundProcessManager", 
    "BackgroundProcess", 
    "ProcessType", 
    "ProcessPriority", 
    "ProcessStatus",
    "background_process_manager"
]
