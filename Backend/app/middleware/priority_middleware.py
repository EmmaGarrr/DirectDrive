import asyncio
import time
from typing import Callable, Dict, Any
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PriorityRequest:
    """Represents a request with priority information"""
    def __init__(self, request_id: str, priority: int, request: Request, timestamp: float):
        self.request_id = request_id
        self.priority = priority  # 1 = Admin (High), 2 = User (Normal)
        self.request = request
        self.timestamp = timestamp
        self.processing_started = False
        self.completed = False

class PriorityQueueManager:
    """Manages request priorities and processing order"""
    
    def __init__(self):
        self.admin_queue = asyncio.Queue()  # Priority 1 - Admin requests
        self.user_queue = asyncio.Queue()   # Priority 2 - User requests
        self.processing_requests: Dict[str, PriorityRequest] = {}
        self.request_counter = 0
        self.admin_workers = 2  # Number of admin workers
        self.user_workers = 3   # Number of user workers
        self._start_workers()
    
    def _start_workers(self):
        """Start background worker tasks"""
        for i in range(self.admin_workers):
            asyncio.create_task(self._admin_worker(f"admin_worker_{i}"))
        
        for i in range(self.user_workers):
            asyncio.create_task(self._user_worker(f"user_worker_{i}"))
        
        logger.info(f"Started {self.admin_workers} admin workers and {self.user_workers} user workers")
    
    async def _admin_worker(self, worker_name: str):
        """Admin worker - processes high-priority requests first"""
        while True:
            try:
                # Process admin requests with higher priority
                if not self.admin_queue.empty():
                    request = await self.admin_queue.get()
                    await self._process_request(request, worker_name)
                else:
                    # If no admin requests, help with user requests
                    if not self.user_queue.empty():
                        request = await self.user_queue.get()
                        await self._process_request(request, worker_name)
                    else:
                        await asyncio.sleep(0.1)  # Small delay when no work
            except Exception as e:
                logger.error(f"Admin worker {worker_name} error: {e}")
                await asyncio.sleep(1)
    
    async def _user_worker(self, worker_name: str):
        """User worker - processes normal priority requests"""
        while True:
            try:
                if not self.user_queue.empty():
                    request = await self.user_queue.get()
                    await self._process_request(request, worker_name)
                else:
                    await asyncio.sleep(0.1)  # Small delay when no work
            except Exception as e:
                logger.error(f"User worker {worker_name} error: {e}")
                await asyncio.sleep(1)
    
    async def _process_request(self, request: PriorityRequest, worker_name: str):
        """Process a single request"""
        try:
            request.processing_started = True
            logger.info(f"Worker {worker_name} processing {request.request_id} (Priority: {request.priority})")
            
            # Simulate processing time (in real implementation, this would be the actual request processing)
            await asyncio.sleep(0.01)  # 10ms simulation
            
            request.completed = True
            logger.info(f"Worker {worker_name} completed {request.request_id}")
            
        except Exception as e:
            logger.error(f"Error processing request {request.request_id}: {e}")
        finally:
            if request.request_id in self.processing_requests:
                del self.processing_requests[request.request_id]
    
    def add_request(self, priority: int, request: Request) -> str:
        """Add a request to the appropriate queue"""
        self.request_counter += 1
        request_id = f"req_{self.request_counter}_{priority}"
        
        priority_request = PriorityRequest(
            request_id=request_id,
            priority=priority,
            request=request,
            timestamp=time.time()
        )
        
        if priority == 1:  # Admin request
            self.admin_queue.put_nowait(priority_request)
            logger.info(f"Added admin request {request_id} to admin queue")
        else:  # User request
            self.user_queue.put_nowait(priority_request)
            logger.info(f"Added user request {request_id} to user queue")
        
        self.processing_requests[request_id] = priority_request
        return request_id
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status for monitoring"""
        return {
            "admin_queue_size": self.admin_queue.qsize(),
            "user_queue_size": self.user_queue.qsize(),
            "processing_count": len(self.processing_requests),
            "admin_workers": self.admin_workers,
            "user_workers": self.user_workers,
            "total_requests_processed": self.request_counter
        }

# Global priority queue manager instance
priority_manager = PriorityQueueManager()

class PriorityMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns priorities to requests based on their type"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Determine request priority
        priority = self._determine_priority(request)
        
        # Add request to priority queue
        request_id = priority_manager.add_request(priority, request)
        
        # Add request ID to request state for tracking
        request.state.request_id = request_id
        request.state.priority = priority
        
        # Log request details
        logger.info(f"Request {request_id} (Priority: {priority}) - {request.method} {request.url.path}")
        
        # Process the request
        try:
            response = await call_next(request)
            
            # Add priority headers to response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Request-Priority"] = str(priority)
            response.headers["X-Processing-Time"] = str(time.time() - start_time)
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing request {request_id}: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "request_id": request_id}
            )
    
    def _determine_priority(self, request: Request) -> int:
        """Determine request priority based on path and headers"""
        path = request.url.path.lower()
        
        # Admin routes get priority 1 (High)
        if any(admin_path in path for admin_path in [
            "/api/v1/admin",
            "/admin",
            "/ws_admin"
        ]):
            return 1
        
        # Check for admin token in headers
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # This is a simplified check - in production, you'd verify the JWT token
            # For now, we'll assume admin routes are properly protected
            pass
        
        # User routes get priority 2 (Normal)
        return 2

# Export the priority manager for use in other parts of the application
__all__ = ["PriorityMiddleware", "priority_manager", "PriorityRequest"]
