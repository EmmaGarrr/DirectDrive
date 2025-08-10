# In file: Backend/app/services/hetzner_service.py

import asyncio
import httpx
import uuid
import traceback

from app.core.config import settings
from app.db.mongodb import db
from app.models.file import BackupStatus, StorageLocation
from app.services import google_drive_service

# The Producer-Consumer functions remain the same
async def producer(queue: asyncio.Queue, gdrive_id: str, account):
    try:
        print("[PRODUCER] Starting download from Google Drive...")
        async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=account):
            await queue.put(chunk)
        print("[PRODUCER] Finished downloading. Placing sentinel in queue.")
        await queue.put(None)
    except Exception as e:
        print(f"!!! [PRODUCER] Error during download: {e}")
        await queue.put(None)
        raise

async def consumer(queue: asyncio.Queue):
    while True:
        chunk = await queue.get()
        if chunk is None:
            print("[CONSUMER] Sentinel received. Ending upload stream.")
            break
        yield chunk
        queue.task_done()

async def transfer_gdrive_to_hetzner(file_id: str):
    if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
        print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
        return

    print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
    try:
        file_doc = db.files.find_one({"_id": file_id})
        if not file_doc:
            print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
            return

        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

        # Prepare common variables
        remote_path = f"{file_id}/{file_doc.get('filename')}"
        auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
        file_size = file_doc.get("size_bytes", 0)

        # Create the directory on Hetzner - this is always required.
        directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
        async with httpx.AsyncClient(auth=auth) as client:
            mkcol_response = await client.request("MKCOL", directory_url)
            if mkcol_response.status_code not in [201, 405]:
                mkcol_response.raise_for_status()

        # --- FINAL FIX: HANDLE 0-BYTE FILES AS A SPECIAL CASE ---
        if file_size == 0:
            print(f"[HETZNER_BACKUP] File {file_id} is 0 bytes. Backup complete after directory creation.")
        else:
            # Only run the complex streaming logic for files with content.
            gdrive_id = file_doc.get("gdrive_id")
            gdrive_account_id = file_doc.get("gdrive_account_id")

            if not gdrive_id or not gdrive_account_id:
                raise ValueError("Missing gdrive_id or gdrive_account_id for non-empty file.")
                
            source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
            if not source_gdrive_account:
                raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

            queue = asyncio.Queue(maxsize=5)
            producer_task = asyncio.create_task(producer(queue, gdrive_id, source_gdrive_account))
            
            headers = {'Content-Length': str(file_size)}
            timeout_config = httpx.Timeout(30.0, read=1800.0, write=1800.0)
            
            file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
            async with httpx.AsyncClient(auth=auth, timeout=timeout_config) as client:
                print(f"[HETZNER_BACKUP] Starting upload to Hetzner from consumer...")
                response = await client.put(file_upload_url, content=consumer(queue), headers=headers)
                response.raise_for_status()

            await producer_task
        # --- END OF FIX ---

        print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.COMPLETED, "backup_location": StorageLocation.HETZNER, "hetzner_remote_path": remote_path}})

    except Exception as e:
        print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
        traceback.print_exc()
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})

class HetznerService:
    """Service for managing Hetzner Storage Box operations"""
    
    async def delete_file(self, remote_path: str) -> bool:
        """
        Delete a file from Hetzner Storage Box using WebDAV
        Returns True if successful, False if file not found, raises exception for other errors.
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            auth = httpx.BasicAuth(settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            file_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
            
            timeout_config = httpx.Timeout(30.0)
            async with httpx.AsyncClient(auth=auth, timeout=timeout_config) as client:
                response = await client.delete(file_url)
                
                if response.status_code == 204:
                    print(f"[HETZNER_DELETE] Successfully deleted file: {remote_path}")
                    return True
                elif response.status_code == 404:
                    print(f"[HETZNER_DELETE] File not found: {remote_path} (404) - already deleted")
                    return False
                else:
                    response.raise_for_status()
                    return True
                    
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print(f"[HETZNER_DELETE] File not found: {remote_path} - already deleted")
                return False
            else:
                print(f"!!! [HETZNER_DELETE] HTTP error deleting file {remote_path}: {e}")
                raise e
        except Exception as e:
            print(f"!!! [HETZNER_DELETE] Unexpected error deleting file {remote_path}: {e}")
            raise e

    async def get_storage_contents(self, path: str = "") -> list:
        """
        Get contents of a directory using WebDAV PROPFIND
        Returns list of file/directory paths
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            auth = httpx.BasicAuth(settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            url = f"{settings.HETZNER_WEBDAV_URL}/{path}".rstrip('/')
            
            # PROPFIND request to get directory contents
            propfind_body = """<?xml version="1.0" encoding="utf-8"?>
<propfind xmlns="DAV:">
    <prop>
        <resourcetype/>
        <getlastmodified/>
        <getcontentlength/>
    </prop>
</propfind>"""
            
            timeout_config = httpx.Timeout(30.0)
            async with httpx.AsyncClient(auth=auth, timeout=timeout_config) as client:
                response = await client.request(
                    "PROPFIND", 
                    url, 
                    content=propfind_body,
                    headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}
                )
                
                if response.status_code in [200, 207]:
                    # Parse XML response to extract file/directory paths
                    # For simplicity, we'll use a regex approach to extract paths
                    import re
                    content = response.text
                    
                    # Extract paths from XML response
                    paths = []
                    # Skip the root directory itself
                    for line in content.split('\n'):
                        if 'href' in line:
                            match = re.search(r'href[^>]*>([^<]+)</href>', line)
                            if match:
                                path = match.group(1).strip()
                                if path and path != '/' and path != f'/{path}':
                                    # Remove leading slash and decode URL
                                    clean_path = path.lstrip('/')
                                    if clean_path:
                                        paths.append(clean_path)
                    
                    return paths
                else:
                    response.raise_for_status()
                    return []
                    
        except Exception as e:
            print(f"!!! [HETZNER_LIST] Error listing contents of {path}: {e}")
            raise e

    async def delete_directory_recursive(self, directory_path: str) -> dict:
        """
        Recursively delete a directory and all its contents
        Returns dict with deletion statistics
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            print(f"[HETZNER_DELETE_DIR] Starting recursive deletion of directory: {directory_path}")
            
            # Get all contents of the directory
            contents = await self.get_storage_contents(directory_path)
            
            deleted_files = 0
            deleted_dirs = 0
            errors = 0
            
            # Delete files first, then directories
            for item_path in contents:
                try:
                    full_path = f"{directory_path}/{item_path}" if directory_path else item_path
                    
                    # Try to delete as file first
                    if await self.delete_file(full_path):
                        deleted_files += 1
                        print(f"[HETZNER_DELETE_DIR] Deleted file: {full_path}")
                    else:
                        # If file deletion fails, try directory deletion
                        if await self.delete_directory(full_path):
                            deleted_dirs += 1
                            print(f"[HETZNER_DELETE_DIR] Deleted directory: {full_path}")
                        else:
                            errors += 1
                            print(f"[HETZNER_DELETE_DIR] Failed to delete: {full_path}")
                            
                except Exception as e:
                    errors += 1
                    print(f"!!! [HETZNER_DELETE_DIR] Error deleting {item_path}: {e}")
            
            # Finally delete the directory itself
            if directory_path:
                try:
                    if await self.delete_directory(directory_path):
                        deleted_dirs += 1
                        print(f"[HETZNER_DELETE_DIR] Deleted root directory: {directory_path}")
                    else:
                        errors += 1
                        print(f"[HETZNER_DELETE_DIR] Failed to delete root directory: {directory_path}")
                except Exception as e:
                    errors += 1
                    print(f"!!! [HETZNER_DELETE_DIR] Error deleting root directory {directory_path}: {e}")
            
            result = {
                "deleted_files": deleted_files,
                "deleted_dirs": deleted_dirs,
                "errors": errors,
                "total_items": len(contents)
            }
            
            print(f"[HETZNER_DELETE_DIR] Recursive deletion completed: {result}")
            return result
            
        except Exception as e:
            print(f"!!! [HETZNER_DELETE_DIR] Error in recursive deletion of {directory_path}: {e}")
            raise e

    async def delete_directory(self, directory_path: str) -> bool:
        """
        Delete an empty directory using WebDAV
        Returns True if successful, False if not found
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            auth = httpx.BasicAuth(settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            dir_url = f"{settings.HETZNER_WEBDAV_URL}/{directory_path}"
            
            timeout_config = httpx.Timeout(30.0)
            async with httpx.AsyncClient(auth=auth, timeout=timeout_config) as client:
                response = await client.delete(dir_url)
                
                if response.status_code == 204:
                    print(f"[HETZNER_DELETE_DIR] Successfully deleted directory: {directory_path}")
                    return True
                elif response.status_code == 404:
                    print(f"[HETZNER_DELETE_DIR] Directory not found: {directory_path} (404)")
                    return False
                else:
                    response.raise_for_status()
                    return True
                    
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print(f"[HETZNER_DELETE_DIR] Directory not found: {directory_path}")
                return False
            else:
                print(f"!!! [HETZNER_DELETE_DIR] HTTP error deleting directory {directory_path}: {e}")
                raise e
        except Exception as e:
            print(f"!!! [HETZNER_DELETE_DIR] Unexpected error deleting directory {directory_path}: {e}")
            raise e

    async def delete_all_files(self) -> dict:
        """
        Delete ALL files and directories from Hetzner storage
        This is a DANGEROUS operation - use with extreme caution!
        Returns dict with deletion statistics
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            print(f"🚨 [HETZNER_DELETE_ALL] STARTING COMPLETE STORAGE CLEANUP!")
            print(f"🚨 [HETZNER_DELETE_ALL] This will delete ALL data from Hetzner storage!")
            
            # Get real storage info before deletion
            storage_info_before = await self.get_storage_info()
            print(f"[HETZNER_DELETE_ALL] Storage before cleanup: {storage_info_before}")
            
            root_contents = await self.get_storage_contents("")
            
            if not root_contents:
                print(f"[HETZNER_DELETE_ALL] No files found in storage - already empty")
                return {
                    "deleted_files": 0,
                    "deleted_dirs": 0,
                    "errors": 0,
                    "total_items": 0,
                    "storage_cleaned": "0 B",
                    "storage_info_before": storage_info_before,
                    "storage_info_after": {"used_bytes": 0, "used_formatted": "0 B", "total_files": 0}
                }
            
            print(f"[HETZNER_DELETE_ALL] Found {len(root_contents)} items to delete")
            
            result = await self.delete_directory_recursive("")
            
            # Get storage info after deletion
            storage_info_after = await self.get_storage_info()
            print(f"[HETZNER_DELETE_ALL] Storage after cleanup: {storage_info_after}")
            
            result["message"] = f"Successfully deleted all {result['total_items']} items from Hetzner storage"
            result["storage_info_before"] = storage_info_before
            result["storage_info_after"] = storage_info_after
            
            print(f"✅ [HETZNER_DELETE_ALL] COMPLETE STORAGE CLEANUP FINISHED: {result}")
            return result
            
        except Exception as e:
            error_msg = f"Failed to delete all files: {str(e)}"
            print(f"!!! [HETZNER_DELETE_ALL] {error_msg}")
            raise Exception(error_msg)

    async def get_storage_info(self) -> dict:
        """
        Get real storage information from Hetzner
        Returns actual storage usage and file count
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            
            # Get root directory contents with depth 1 to get file count and sizes
            async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
                # Use PROPFIND with depth 1 to get immediate children
                headers = {
                    'Depth': '1',
                    'Content-Type': 'application/xml; charset="utf-8"'
                }
                
                propfind_body = '''<?xml version="1.0" encoding="utf-8"?>
                <propfind xmlns="DAV:">
                    <prop>
                        <resourcetype/>
                        <getcontentlength/>
                        <getlastmodified/>
                    </prop>
                </propfind>'''
                
                response = await client.request(
                    "PROPFIND", 
                    settings.HETZNER_WEBDAV_URL, 
                    content=propfind_body,
                    headers=headers
                )
                response.raise_for_status()
                
                # Parse XML response to get file count and total size
                xml_content = response.text
                
                # Simple XML parsing for file count and sizes
                total_files = 0
                total_size = 0
                
                # Count files (not directories) and sum their sizes
                lines = xml_content.split('\n')
                for line in lines:
                    if '<resourcetype/>' in line:  # This indicates a file (no sub-resources)
                        total_files += 1
                    elif '<getcontentlength>' in line:
                        # Extract size from <getcontentlength>1234</getcontentlength>
                        size_start = line.find('<getcontentlength>') + len('<getcontentlength>')
                        size_end = line.find('</getcontentlength>')
                        if size_start > 0 and size_end > size_start:
                            try:
                                size = int(line[size_start:size_end])
                                total_size += size
                            except ValueError:
                                pass
                
                # Format storage size
                def format_bytes(bytes_value):
                    if bytes_value == 0:
                        return "0 B"
                    k = 1024
                    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
                    i = 0
                    while bytes_value >= k and i < len(sizes) - 1:
                        bytes_value /= k
                        i += 1
                    return f"{bytes_value:.2f} {sizes[i]}"
                
                return {
                    "used_bytes": total_size,
                    "used_formatted": format_bytes(total_size),
                    "total_files": total_files,
                    "timestamp": "now"
                }
                
        except Exception as e:
            print(f"!!! [HETZNER_STORAGE_INFO] Failed to get storage info: {e}")
            return {
                "used_bytes": 0,
                "used_formatted": "Unknown",
                "total_files": 0,
                "error": str(e),
                "timestamp": "error"
            }
