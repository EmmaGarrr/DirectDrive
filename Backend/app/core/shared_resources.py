"""
Shared resources for the application.
This module contains resources that need to be accessed by multiple modules.
"""
import asyncio

# Semaphore to limit concurrent downloads
download_semaphore = asyncio.Semaphore(5)  # Adjust the number as needed

# Semaphore to limit concurrent backup tasks
backup_task_semaphore = asyncio.Semaphore(1)
