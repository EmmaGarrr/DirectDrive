from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import logging
from typing import Dict, Tuple, List

# Configure rate limiter logging
rate_limit_logger = logging.getLogger('directdrive.ratelimit')

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
        """
        Rate limiting for anonymous users (IP-based with 2GB daily limit).
        """
        async with self._lock:
            rate_limit_logger.info(f"Anonymous rate limit check - IP: {ip}, Size: {file_size} bytes")
            
            count, first_time, total_bytes = self.ip_uploads[ip]
            now = datetime.now()
            
            # Reset after 24 hours
            if now - first_time > timedelta(hours=24):
                self.ip_uploads[ip] = (1, now, file_size)
                self.active_uploads[ip] = 1
                rate_limit_logger.info(f"Rate limit reset for IP: {ip}")
                return True, "OK"
            
            # Max 2GB per IP per 24 hours for anonymous users
            if total_bytes + file_size > 2147483648:
                remaining = 2147483648 - total_bytes
                rate_limit_logger.warning(f"Daily limit exceeded for IP: {ip}, Remaining: {remaining} bytes")
                return False, f"Daily limit exceeded. {remaining / 1073741824:.2f}GB remaining out of 2GB for anonymous users"
            
            # Max 3 concurrent uploads per IP for anonymous users
            if self.active_uploads[ip] >= 3:
                rate_limit_logger.warning(f"Concurrent upload limit exceeded for IP: {ip}")
                return False, "Too many concurrent uploads. Max 3 allowed for anonymous users"
            
            # Update counters
            self.ip_uploads[ip] = (count + 1, first_time, total_bytes + file_size)
            self.active_uploads[ip] += 1
            
            rate_limit_logger.info(f"Rate limit passed for IP: {ip}, Total used: {total_bytes + file_size} bytes")
            return True, "OK"
    
    async def release_upload(self, ip: str):
        async with self._lock:
            if self.active_uploads[ip] > 0:
                self.active_uploads[ip] -= 1

    async def check_authenticated_rate_limit(self, user_email: str, file_size: int, user_storage_limit: int) -> Tuple[bool, str]:
        """
        Rate limiting for authenticated users with higher limits based on their storage quota.
        Uses user email instead of IP for tracking.
        """
        async with self._lock:
            rate_limit_logger.info(f"Authenticated rate limit check - User: {user_email}, Size: {file_size} bytes, Limit: {user_storage_limit} bytes")
            
            # For authenticated users, we track by email instead of IP
            count, first_time, total_bytes = self.ip_uploads.get(user_email, (0, datetime.now(), 0))
            now = datetime.now()
            
            # Reset after 24 hours
            if now - first_time > timedelta(hours=24):
                self.ip_uploads[user_email] = (1, now, file_size)
                self.active_uploads[user_email] = 1
                rate_limit_logger.info(f"Rate limit reset for user: {user_email}")
                return True, "OK"
            
            # Check user's storage limit (typically 10GB for authenticated users)
            if total_bytes + file_size > user_storage_limit:
                remaining = user_storage_limit - total_bytes
                rate_limit_logger.warning(f"Storage limit exceeded for user: {user_email}, Remaining: {remaining} bytes")
                return False, f"Storage limit exceeded. {remaining} bytes remaining out of {user_storage_limit / 1073741824:.1f}GB"
            
            # Higher concurrent upload limit for authenticated users (5 instead of 3)
            if self.active_uploads.get(user_email, 0) >= 5:
                rate_limit_logger.warning(f"Concurrent upload limit exceeded for user: {user_email}")
                return False, "Too many concurrent uploads. Max 5 allowed for authenticated users"
            
            # Update counters
            self.ip_uploads[user_email] = (count + 1, first_time, total_bytes + file_size)
            self.active_uploads[user_email] = self.active_uploads.get(user_email, 0) + 1
            
            rate_limit_logger.info(f"Rate limit passed for user: {user_email}, Total used: {total_bytes + file_size} bytes")
            return True, "OK"
    
    async def check_user_storage_quota(self, user_email: str, file_size: int, current_storage_used: int, storage_limit: int) -> Tuple[bool, str]:
        """
        Check if user has enough storage quota remaining for the upload.
        This is separate from rate limiting and focuses purely on storage quotas.
        """
        rate_limit_logger.info(f"Storage quota check - User: {user_email}, File size: {file_size}, Used: {current_storage_used}, Limit: {storage_limit}")
        
        remaining_storage = storage_limit - current_storage_used
        if file_size > remaining_storage:
            rate_limit_logger.warning(f"Storage quota exceeded for user: {user_email}, Remaining: {remaining_storage} bytes")
            return False, f"Not enough storage space. {remaining_storage / 1073741824:.2f}GB remaining out of {storage_limit / 1073741824:.1f}GB total"
        
        return True, "OK"
    
    async def release_authenticated_upload(self, user_email: str):
        """
        Release an upload slot for an authenticated user.
        """
        async with self._lock:
            if self.active_uploads.get(user_email, 0) > 0:
                self.active_uploads[user_email] -= 1
                rate_limit_logger.info(f"Released upload slot for user: {user_email}, Active uploads: {self.active_uploads[user_email]}")

rate_limiter = UploadRateLimiter()
