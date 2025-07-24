from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
from typing import Dict, Tuple, List

class UploadRateLimiter:
    def __init__(self):
        # IP -> (upload_count, first_upload_time, total_bytes)
        self.ip_uploads: Dict[str, Tuple[int, datetime, int]] = defaultdict(
            lambda: (0, datetime.now(), 0)
        )
        self.active_uploads: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        
    async def check_upload_size_limit(self, file_size: int) -> Tuple[bool, str]:
        """
        Check if a single file upload exceeds 2GB limit (for anonymous users).
        """
        max_size = 2147483648  # 2GB in bytes
        if file_size > max_size:
            return False, f"File size {file_size} bytes exceeds maximum allowed size of {max_size} bytes (2GB)"
        return True, "OK"
    
    async def check_authenticated_upload_size_limit(self, file_size: int, max_size: int) -> Tuple[bool, str]:
        """
        Check if a single file upload exceeds specified limit (for authenticated users).
        """
        if file_size > max_size:
            max_gb = max_size / 1073741824  # Convert to GB
            return False, f"File size {file_size} bytes exceeds maximum allowed size of {max_size} bytes ({max_gb:.0f}GB)"
        return True, "OK"
    
    async def check_batch_upload_size_limit(self, file_sizes: List[int]) -> Tuple[bool, str]:
        """
        Check if batch upload total size exceeds 2GB limit (for anonymous users).
        """
        total_size = sum(file_sizes)
        max_size = 2147483648  # 2GB in bytes
        if total_size > max_size:
            return False, f"Total batch size {total_size} bytes exceeds maximum allowed size of {max_size} bytes (2GB)"
        return True, "OK"
        
    async def check_authenticated_batch_upload_size_limit(self, file_sizes: List[int], max_size: int) -> Tuple[bool, str]:
        """
        Check if batch upload total size exceeds specified limit (for authenticated users).
        """
        total_size = sum(file_sizes)
        if total_size > max_size:
            max_gb = max_size / 1073741824  # Convert to GB
            return False, f"Total batch size {total_size} bytes exceeds maximum allowed size of {max_size} bytes ({max_gb:.0f}GB)"
        return True, "OK"
        
    async def check_rate_limit(self, ip: str, file_size: int) -> Tuple[bool, str]:
        async with self._lock:
            count, first_time, total_bytes = self.ip_uploads[ip]
            now = datetime.now()
            
            # Reset after 24 hours
            if now - first_time > timedelta(hours=24):
                self.ip_uploads[ip] = (1, now, file_size)
                self.active_uploads[ip] = 1
                return True, "OK"
            
            # Max 2GB per IP per 24 hours
            if total_bytes + file_size > 2147483648:
                remaining = 2147483648 - total_bytes
                return False, f"Daily limit exceeded. {remaining} bytes remaining"
            
            # Max 3 concurrent uploads per IP
            if self.active_uploads[ip] >= 3:
                return False, "Too many concurrent uploads. Max 3 allowed"
            
            # Update counters
            self.ip_uploads[ip] = (count + 1, first_time, total_bytes + file_size)
            self.active_uploads[ip] += 1
            return True, "OK"
    
    async def release_upload(self, ip: str):
        async with self._lock:
            if self.active_uploads[ip] > 0:
                self.active_uploads[ip] -= 1

rate_limiter = UploadRateLimiter()
