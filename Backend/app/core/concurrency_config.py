# File: Backend/app/core/concurrency_config.py

import asyncio
from typing import Dict, Any
import psutil
import os

class ConcurrencyManager:
    """
    Manages concurrency limits and resource allocation for ZIP downloads
    and file operations to prevent server overload.
    """
    
    def __init__(self):
        # Dynamic limits based on available system resources
        self.available_memory = psutil.virtual_memory().available
        self.cpu_count = psutil.cpu_count()
        
        # Calculate safe limits for 4GB RAM system
        memory_gb = self.available_memory / (1024**3)
        
        # Conservative limits for 4GB system
        if memory_gb <= 4:
            self.max_concurrent_zips = 2  # Only 2 ZIP operations at once
            self.max_concurrent_downloads = 10  # Max file downloads
            self.zip_temp_size_limit = 500 * 1024 * 1024  # 500MB temp files max
        elif memory_gb <= 8:
            self.max_concurrent_zips = 4
            self.max_concurrent_downloads = 20
            self.zip_temp_size_limit = 1024 * 1024 * 1024  # 1GB
        else:
            self.max_concurrent_zips = 8
            self.max_concurrent_downloads = 50
            self.zip_temp_size_limit = 2 * 1024 * 1024 * 1024  # 2GB
        
        # Create semaphores for limiting concurrent operations
        self.zip_semaphore = asyncio.Semaphore(self.max_concurrent_zips)
        self.download_semaphore = asyncio.Semaphore(self.max_concurrent_downloads)
        
        # Track active operations
        self.active_zip_operations: Dict[str, Dict[str, Any]] = {}
        
        print(f"[CONCURRENCY] Initialized with limits:")
        print(f"  - Memory: {memory_gb:.1f}GB available")
        print(f"  - Max concurrent ZIPs: {self.max_concurrent_zips}")
        print(f"  - Max concurrent downloads: {self.max_concurrent_downloads}")
        print(f"  - Temp file size limit: {self.zip_temp_size_limit / (1024**2):.0f}MB")
    
    async def acquire_zip_slot(self, batch_id: str) -> bool:
        """
        Acquire a slot for ZIP operation. Returns True if acquired, False if rejected.
        """
        if len(self.active_zip_operations) >= self.max_concurrent_zips:
            print(f"[CONCURRENCY] Rejecting ZIP request for batch {batch_id} - too many active operations")
            return False
        
        await self.zip_semaphore.acquire()
        self.active_zip_operations[batch_id] = {
            'start_time': asyncio.get_event_loop().time(),
            'temp_size': 0
        }
        print(f"[CONCURRENCY] Acquired ZIP slot for batch {batch_id} ({len(self.active_zip_operations)}/{self.max_concurrent_zips} active)")
        return True
    
    def release_zip_slot(self, batch_id: str):
        """
        Release a ZIP operation slot.
        """
        if batch_id in self.active_zip_operations:
            del self.active_zip_operations[batch_id]
            self.zip_semaphore.release()
            print(f"[CONCURRENCY] Released ZIP slot for batch {batch_id} ({len(self.active_zip_operations)}/{self.max_concurrent_zips} active)")
    
    def update_temp_size(self, batch_id: str, size: int):
        """
        Update the temporary file size for a ZIP operation.
        """
        if batch_id in self.active_zip_operations:
            self.active_zip_operations[batch_id]['temp_size'] = size
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current system resource usage and operation status.
        """
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        return {
            'memory': {
                'total_gb': memory.total / (1024**3),
                'available_gb': memory.available / (1024**3),
                'used_percent': memory.percent
            },
            'cpu_percent': cpu_percent,
            'active_operations': {
                'zip_count': len(self.active_zip_operations),
                'zip_details': self.active_zip_operations
            },
            'limits': {
                'max_concurrent_zips': self.max_concurrent_zips,
                'max_concurrent_downloads': self.max_concurrent_downloads,
                'zip_temp_size_limit_mb': self.zip_temp_size_limit / (1024**2)
            }
        }

# Global instance
concurrency_manager = ConcurrencyManager()
