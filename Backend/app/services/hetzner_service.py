# In file: Backend/app/services/hetzner_service.py

import asyncio
import httpx
import uuid
import traceback
import re
import time

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
        Returns list of objects with file/directory information
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            auth = httpx.BasicAuth(settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            # Ensure directories end with trailing slash to avoid 301 redirects
            if path == "/":
                url = settings.HETZNER_WEBDAV_URL.rstrip('/')
            elif path.endswith('/'):
                url = f"{settings.HETZNER_WEBDAV_URL}/{path}"
            else:
                url = f"{settings.HETZNER_WEBDAV_URL}/{path}/"
            
            print(f"🔍 [GET_CONTENTS] Fetching contents from: {url}")
            
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
                    # Parse XML response to extract file/directory information
                    import re
                    content = response.text
                    
                    print(f"📄 [GET_CONTENTS] Response length: {len(content)} characters")
                    print(f"📄 [GET_CONTENTS] Response sample: {content[:500]}...")
                    
                    # Extract paths and properties from XML response
                    items = []
                    
                    # Find all response blocks - handle different namespace prefixes
                    response_blocks = re.findall(r'<[^:]*:response[^>]*>(.*?)</[^:]*:response>', content, re.DOTALL)
                    print(f"📊 [GET_CONTENTS] Found {len(response_blocks)} response blocks")
                    
                    for i, block in enumerate(response_blocks):
                        # Extract href (path) - handle different namespace prefixes
                        href_match = re.search(r'<[^:]*:href>([^<]+)</[^:]*:href>', block)
                        if not href_match:
                            continue
                        
                        href = href_match.group(1).strip()
                        
                    # Skip the root directory itself
                        if href == '/' or href == f'/{path}' or href == f'/{path}/':
                            print(f"🔄 [GET_CONTENTS] Skipping root path: {href}")
                            continue
                        
                        # Check if it's a directory or file
                        resourcetype_match = re.search(r'<[^:]*:resourcetype>.*?</[^:]*:resourcetype>', block, re.DOTALL)
                        is_directory = resourcetype_match and '<D:collection/>' in resourcetype_match.group(0)
                        
                        # Extract size for files
                        size = 0
                        if not is_directory:
                            size_match = re.search(r'<[^:]*:getcontentlength>([^<]+)</[^:]*:getcontentlength>', block)
                            if size_match:
                                try:
                                    size = int(size_match.group(1))
                                except ValueError:
                                    size = 0
                        
                        # Clean the path name
                        clean_path = href.lstrip('/')
                        if is_directory:
                            clean_path = clean_path.rstrip('/')
                        
                        if clean_path and clean_path not in [path, '']:
                            items.append({
                                'name': clean_path,
                                'is_directory': is_directory,
                                'size': size
                            })
                            
                            if is_directory:
                                print(f"📁 [GET_CONTENTS] Found directory: {clean_path}/")
                            else:
                                print(f"📄 [GET_CONTENTS] Found file: {clean_path} (size: {size} bytes)")
                    
                    print(f"✅ [GET_CONTENTS] Total items found: {len(items)}")
                    return items
                else:
                    print(f"❌ [GET_CONTENTS] HTTP {response.status_code} for {url}")
                    response.raise_for_status()
                    return []
                    
        except Exception as e:
            print(f"❌ [GET_CONTENTS] Error listing contents of {path}: {e}")
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

    async def delete_all_files_force(self) -> dict:
        """
        Force delete ALL files and directories from Hetzner storage WITHOUT scanning
        This is a DANGEROUS operation - use with extreme caution!
        Much faster than delete_all_files() as it skips storage scanning
        Returns dict with deletion statistics
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            print(f"💥 [HETZNER_FORCE_DELETE] STARTING FORCE STORAGE CLEANUP!")
            print(f"💥 [HETZNER_FORCE_DELETE] This will delete ALL data from Hetzner storage WITHOUT scanning!")
            
            # Skip storage scanning - go straight to deletion
            print(f"[HETZNER_FORCE_DELETE] Skipping storage scan - proceeding directly to deletion")
            
            root_contents = await self.get_storage_contents("")
            
            if not root_contents:
                print(f"[HETZNER_FORCE_DELETE] No files found in storage - already empty")
                return {
                    "deleted_files": 0,
                    "deleted_dirs": 0,
                    "errors": 0,
                    "total_items": 0,
                    "storage_cleaned": "0 B",
                    "storage_info_before": {"used_bytes": 0, "used_formatted": "0 B", "total_files": 0},
                    "storage_info_after": {"used_bytes": 0, "used_formatted": "0 B", "total_files": 0}
                }
            
            print(f"[HETZNER_FORCE_DELETE] Found {len(root_contents)} items to delete")
            
            result = await self.delete_directory_recursive("")
            
            # For force delete, we don't scan after deletion to save time
            # Just assume everything was deleted successfully
            storage_info_after = {"used_bytes": 0, "used_formatted": "0 B", "total_files": 0}
            
            result["message"] = f"Force delete completed: {result['total_items']} items deleted from Hetzner storage"
            result["storage_info_before"] = {"used_bytes": "Unknown (force delete mode)", "used_formatted": "Unknown", "total_files": "Unknown"}
            result["storage_info_after"] = storage_info_after
            
            print(f"💥 [HETZNER_FORCE_DELETE] FORCE STORAGE CLEANUP FINISHED: {result}")
            return result
            
        except Exception as e:
            error_msg = f"Failed to force delete all files: {str(e)}"
            print(f"!!! [HETZNER_FORCE_DELETE] {error_msg}")
            raise Exception(error_msg)

    async def get_storage_info(self) -> dict:
        """
        Get comprehensive storage information from Hetzner
        Returns dict with file count, total size, and formatted size
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            print(f"🚀 [STORAGE_INFO] Starting comprehensive storage scan...")
            
            # Start recursive scanning from root
            scan_result = await self._scan_storage_recursive("/", set())
            
            total_files = len(scan_result.get("files", []))
            total_size = scan_result.get("total_size", 0)
            total_size_formatted = self._format_bytes(total_size)
            
            print(f"✅ [STORAGE_INFO] Scan completed: {total_files} files, {total_size_formatted}")
            
            return {
                "total_files": total_files,
                "total_size": total_size,
                "total_size_formatted": total_size_formatted,
                "scan_method": "recursive_parallel_ready"
            }
            
        except Exception as e:
            print(f"❌ [STORAGE_INFO] Error getting storage info: {e}")
            raise e

    async def _scan_storage_recursive(self, path: str, visited_paths: set = None) -> dict:
        """
        Recursively scan storage starting from a given path
        Returns dict with file count, total size, and subdirectory count
        """
        if visited_paths is None:
            visited_paths = set()
        
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            # Normalize path and check for loops
            normalized_path = path.rstrip('/')
            if normalized_path in visited_paths:
                print(f"🔄 [SCAN] Skipping already visited path: {normalized_path}")
                return {"files": [], "total_size": 0, "subdirectories": 0}
            
            visited_paths.add(normalized_path)
            
            # Construct URL with proper trailing slash for directories
            if path.endswith('/'):
                url = f"{settings.HETZNER_WEBDAV_URL}/{path}"
            else:
                url = f"{settings.HETZNER_WEBDAV_URL}/{path}/"
            
            print(f"🔍 [SCAN] Scanning: {path} (URL: {url})")
            
            auth = httpx.BasicAuth(settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            
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
                    # Parse XML response using regex for namespace-agnostic extraction
                    import re
                    content = response.text
                    
                    # Extract file and directory information
                    files = []
                    directories = []
                    total_size = 0
                    
                    # Find all response blocks
                    response_blocks = re.findall(r'<D:response[^>]*>(.*?)</D:response>', content, re.DOTALL)
                    print(f"📊 [SCAN] Found {len(response_blocks)} response blocks")
                    
                    for block in response_blocks:
                        # Extract href (path)
                        href_match = re.search(r'<D:href>([^<]+)</D:href>', block)
                        if not href_match:
                            continue
                        
                        href = href_match.group(1).strip()
                        
                        # Skip the current directory itself
                        if href == f"/{path}" or href == f"/{path}/" or href == "/":
                            continue
                        
                        # Extract size and check if it's a directory
                        size_match = re.search(r'<[^:]*:getcontentlength>([^<]+)</[^:]*:getcontentlength>', block)
                        resourcetype_match = re.search(r'<[^:]*:resourcetype>.*?</[^:]*:resourcetype>', block, re.DOTALL)
                        
                        is_directory = resourcetype_match and '<D:collection/>' in resourcetype_match.group(0)
                        
                        if is_directory:
                            # It's a directory
                            dir_name = href.rstrip('/').split('/')[-1]
                            if dir_name and dir_name not in [path, '']:
                                directories.append(dir_name)
                                print(f"📁 [SCAN] Found directory: {dir_name}/")
                        else:
                            # It's a file
                            file_name = href.split('/')[-1]
                            if file_name:
                                size = 0
                                if size_match:
                                    try:
                                        size = int(size_match.group(1))
                                    except ValueError:
                                        size = 0
                                
                                files.append({"name": file_name, "size": size})
                                total_size += size
                                print(f"📄 [SCAN] Found file: {file_name} (size: {size} bytes)")
                    
                    # Recursively scan subdirectories
                    subdirectory_files = []
                    subdirectory_size = 0
                    
                    for directory in directories:
                        try:
                            sub_path = f"{path}/{directory}" if path else directory
                            sub_result = await self._scan_storage_recursive(sub_path, visited_paths)
                            subdirectory_files.extend(sub_result.get("files", []))
                            subdirectory_size += sub_result.get("total_size", 0)
                            
                            # Small delay to avoid overwhelming the server
                            await asyncio.sleep(0.05)
                            
                        except Exception as e:
                            print(f"⚠️ [SCAN] Error scanning subdirectory {directory}: {e}")
                            continue
                    
                    # Combine all results
                    all_files = files + subdirectory_files
                    total_size += subdirectory_size
                    
                    print(f"✅ [SCAN] Path {path}: {len(all_files)} files, {self._format_bytes(total_size)}, {len(directories)} subdirectories")
                    
                    return {
                        "files": all_files,
                        "total_size": total_size,
                        "subdirectories": len(directories)
                    }
                    
                else:
                    print(f"❌ [SCAN] HTTP {response.status_code} for {path}")
                    response.raise_for_status()
                    return {"files": [], "total_size": 0, "subdirectories": 0}
                    
        except Exception as e:
            print(f"❌ [SCAN] Error scanning {path}: {e}")
            return {"files": [], "total_size": 0, "subdirectories": 0}

    async def parallel_storage_cleanup(self) -> dict:
        """
        HYBRID APPROACH: Fast parallel scanning + parallel deletion
        Uses 5 workers for both scanning and deletion
        Reduces 10+ minutes to ~3-4 minutes total
        """
        if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            raise Exception("Hetzner credentials not configured")
        
        try:
            print(f"🚀 [HETZNER_PARALLEL] STARTING HYBRID PARALLEL STORAGE CLEANUP!")
            print(f"🚀 [HETZNER_PARALLEL] Using 5 workers for scanning + 5 workers for deletion")
            
            # STEP 1: Fast Parallel Scanning (5 workers)
            print(f"[HETZNER_PARALLEL] STEP 1: Fast parallel scanning with 5 workers...")
            scan_start_time = time.time()
            
            all_files = await self._scan_storage_parallel_5_workers()
            scan_time = time.time() - scan_start_time
            
            print(f"[HETZNER_PARALLEL] Parallel scan completed in {scan_time:.2f}s")
            print(f"[HETZNER_PARALLEL] Found {len(all_files)} files to delete")
            
            if not all_files:
                print(f"[HETZNER_PARALLEL] No files found - storage already empty")
                return {
                    "deleted_files": 0,
                    "deleted_dirs": 0,
                    "errors": 0,
                    "total_items": 0,
                    "scan_time": scan_time,
                    "delete_time": 0,
                    "total_time": scan_time,
                    "parallel_mode": True
                }
            
            # STEP 2: Fast Parallel Deletion (5 workers)
            print(f"[HETZNER_PARALLEL] STEP 2: Fast parallel deletion with 5 workers...")
            delete_start_time = time.time()
            
            deletion_result = await self._delete_files_parallel_5_workers(all_files)
            delete_time = time.time() - delete_start_time
            
            total_time = time.time() - scan_start_time
            
            print(f"[HETZNER_PARALLEL] Parallel deletion completed in {delete_time:.2f}s")
            print(f"[HETZNER_PARALLEL] Total operation time: {total_time:.2f}s")
            
            # Combine results
            result = {
                "message": f"Parallel cleanup completed: {deletion_result['deleted_files']} files deleted in {total_time:.2f}s",
                "deleted_files": deletion_result.get("deleted_files", 0),
                "deleted_dirs": deletion_result.get("deleted_dirs", 0),
                "errors": deletion_result.get("errors", 0),
                "total_items": deletion_result.get("total_items", 0),
                "scan_time": scan_time,
                "delete_time": delete_time,
                "total_time": total_time,
                "parallel_mode": True,
                "workers_used": 5
            }
            
            print(f"🚀 [HETZNER_PARALLEL] HYBRID PARALLEL CLEANUP COMPLETED: {result}")
            return result
            
        except Exception as e:
            error_msg = f"Failed to perform parallel storage cleanup: {str(e)}"
            print(f"!!! [HETZNER_PARALLEL] {error_msg}")
            raise Exception(error_msg)

    async def _scan_storage_parallel_5_workers(self) -> list:
        """
        Scan storage using 5 parallel workers
        Returns list of all files found
        """
        try:
            print(f"[PARALLEL_SCAN] Starting parallel scan with 5 workers...")
            
            # Get root contents first
            root_contents = await self.get_storage_contents("")
            if not root_contents:
                return []
            
            # Split directories into 5 chunks for parallel processing
            directories = [item for item in root_contents if item.get('is_directory', False)]
            files = [item for item in root_contents if not item.get('is_directory', False)]
            
            print(f"[PARALLEL_SCAN] Root: {len(directories)} directories, {len(files)} files")
            
            if not directories:
                # Only files at root level
                return files
            
            # Split directories into 5 chunks
            chunk_size = max(1, len(directories) // 5)
            directory_chunks = [directories[i:i + chunk_size] for i in range(0, len(directories), chunk_size)]
            
            print(f"[PARALLEL_SCAN] Split into {len(directory_chunks)} chunks for parallel processing")
            
            # Create tasks for parallel scanning
            tasks = []
            for i, chunk in enumerate(directory_chunks):
                task = self._scan_directory_chunk_worker(i, chunk)
                tasks.append(task)
            
            # Execute all tasks in parallel
            print(f"[PARALLEL_SCAN] Executing {len(tasks)} parallel scan tasks...")
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combine all results
            all_files = files.copy()  # Start with root files
            for i, result in enumerate(chunk_results):
                if isinstance(result, Exception):
                    print(f"[PARALLEL_SCAN] Worker {i} failed: {result}")
                    continue
                all_files.extend(result)
            
            print(f"[PARALLEL_SCAN] Parallel scan completed. Total files found: {len(all_files)}")
            return all_files
            
        except Exception as e:
            print(f"!!! [PARALLEL_SCAN] Error in parallel scan: {e}")
            raise e

    async def _scan_directory_chunk_worker(self, worker_id: int, directories: list) -> list:
        """
        Worker function for scanning a chunk of directories
        """
        try:
            print(f"[WORKER_{worker_id}] Starting scan of {len(directories)} directories")
            worker_files = []
            
            for directory in directories:
                dir_path = directory.get('name', '')
                if not dir_path:
                    continue
                
                try:
                    # Scan this directory recursively
                    dir_contents = await self._scan_directory_recursive_worker(worker_id, dir_path)
                    worker_files.extend(dir_contents)
                    
                    # Small delay to avoid overwhelming the server
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    print(f"[WORKER_{worker_id}] Error scanning directory {dir_path}: {e}")
                    continue
            
            print(f"[WORKER_{worker_id}] Completed scan. Found {len(worker_files)} files")
            return worker_files
            
        except Exception as e:
            print(f"!!! [WORKER_{worker_id}] Worker failed: {e}")
            raise e

    async def _scan_directory_recursive_worker(self, worker_id: int, directory_path: str) -> list:
        """
        Recursively scan a single directory (worker version)
        """
        try:
            files = []
            visited_paths = set()
            
            async def scan_recursive(path: str):
                if path in visited_paths:
                    return
                visited_paths.add(path)
                
                try:
                    contents = await self.get_storage_contents(path)
                    if not contents:
                        return
                    
                    for item in contents:
                        if not item.get('is_directory', False):
                            # It's a file
                            files.append(item)
                        else:
                            # It's a directory, scan recursively
                            sub_path = f"{path}/{item['name']}" if path else item['name']
                            await scan_recursive(sub_path)
                            
                except Exception as e:
                    print(f"[WORKER_{worker_id}] Error scanning path {path}: {e}")
                    return
            
            await scan_recursive(directory_path)
            return files
            
        except Exception as e:
            print(f"!!! [WORKER_{worker_id}] Recursive scan failed for {directory_path}: {e}")
            return []

    async def _delete_files_parallel_5_workers(self, all_files: list) -> dict:
        """
        Delete files using 5 parallel workers
        """
        try:
            print(f"[PARALLEL_DELETE] Starting parallel deletion with 5 workers...")
            print(f"[PARALLEL_DELETE] Total files to delete: {len(all_files)}")
            
            if not all_files:
                return {"deleted_files": 0, "deleted_dirs": 0, "errors": 0, "total_items": 0}
            
            # Split files into 5 chunks
            chunk_size = max(1, len(all_files) // 5)
            file_chunks = [all_files[i:i + chunk_size] for i in range(0, len(all_files), chunk_size)]
            
            print(f"[PARALLEL_DELETE] Split into {len(file_chunks)} chunks for parallel deletion")
            
            # Create tasks for parallel deletion
            tasks = []
            for i, chunk in enumerate(file_chunks):
                task = self._delete_chunk_worker(i, chunk)
                tasks.append(task)
            
            # Execute all tasks in parallel
            print(f"[PARALLEL_DELETE] Executing {len(tasks)} parallel deletion tasks...")
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combine all results
            total_deleted_files = 0
            total_deleted_dirs = 0
            total_errors = 0
            
            for i, result in enumerate(chunk_results):
                if isinstance(result, Exception):
                    print(f"[PARALLEL_DELETE] Worker {i} failed: {result}")
                    total_errors += 1
                    continue
                
                total_deleted_files += result.get("deleted_files", 0)
                total_deleted_dirs += result.get("deleted_dirs", 0)
                total_errors += result.get("errors", 0)
            
            result = {
                "deleted_files": total_deleted_files,
                "deleted_dirs": total_deleted_dirs,
                "errors": total_errors,
                "total_items": total_deleted_files + total_deleted_dirs
            }
            
            print(f"[PARALLEL_DELETE] Parallel deletion completed: {result}")
            return result
                
        except Exception as e:
            print(f"!!! [PARALLEL_DELETE] Error in parallel deletion: {e}")
            raise e

    async def _delete_chunk_worker(self, worker_id: int, files: list) -> dict:
        """
        Worker function for deleting a chunk of files
        """
        try:
            print(f"[DELETE_WORKER_{worker_id}] Starting deletion of {len(files)} files")
            deleted_files = 0
            deleted_dirs = 0
            errors = 0
            
            for file_item in files:
                try:
                    file_path = file_item.get('name', '')
                    if not file_path:
                        continue
                    
                    if file_item.get('is_directory', False):
                        # Delete directory
                        await self.delete_directory(file_path)
                        deleted_dirs += 1
                    else:
                        # Delete file
                        await self.delete_file(file_path)
                        deleted_files += 1
                    
                    # Small delay to avoid overwhelming the server
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    print(f"[DELETE_WORKER_{worker_id}] Error deleting {file_item.get('name', 'unknown')}: {e}")
                    errors += 1
                    continue
            
            print(f"[DELETE_WORKER_{worker_id}] Completed deletion. Files: {deleted_files}, Dirs: {deleted_dirs}, Errors: {errors}")
            return {
                "deleted_files": deleted_files,
                "deleted_dirs": deleted_dirs,
                "errors": errors
            }
            
        except Exception as e:
            print(f"!!! [DELETE_WORKER_{worker_id}] Worker failed: {e}")
            raise e

    async def auto_parallel_scan_with_progress(self) -> dict:
        """
        Perform fast parallel scanning with progress updates
        Uses 5 workers for faster scanning
        """
        try:
            print("🚀 [FAST_PARALLEL_SCAN] Starting fast parallel scan with 5 workers...")
            
            # Get root directory contents first
            root_contents = await self.get_storage_contents("")
            
            if not root_contents:
                print("❌ [FAST_PARALLEL_SCAN] Storage is empty")
                return {
                    'status': 'completed',
                    'total_files': 0,
                    'total_size': 0,
                    'total_size_formatted': '0 B',
                    'progress': 100,
                    'message': 'Storage is empty',
                    'parallel_mode': True,
                    'workers_used': 5
                }
            
            # Separate directories and files
            directories = [item['name'] for item in root_contents if item['is_directory']]
            root_files = [item for item in root_contents if not item['is_directory']]
            
            print(f"📊 [FAST_PARALLEL_SCAN] Found {len(directories)} directories and {len(root_files)} files at root")
            
            # Calculate total items for progress tracking
            total_items = len(directories)
            if total_items == 0:
                # Only root files exist
                total_size = sum(item['size'] for item in root_files)
                total_size_formatted = self._format_bytes(total_size)
                print(f"✅ [FAST_PARALLEL_SCAN] Only root files found: {len(root_files)} files, {total_size_formatted}")
                return {
                    'status': 'completed',
                    'total_files': len(root_files),
                    'total_size': total_size,
                    'total_size_formatted': total_size_formatted,
                    'progress': 100,
                    'message': f'Found {len(root_files)} files at root level',
                    'parallel_mode': True,
                    'workers_used': 5
                }
            
            # Split directories among workers
            chunk_size = max(1, len(directories) // 5)
            chunks = [directories[i:i + chunk_size] for i in range(0, len(directories), chunk_size)]
            
            print(f"🔧 [FAST_PARALLEL_SCAN] Distributing {len(directories)} directories among {len(chunks)} workers")
            
            # Start parallel scanning
            tasks = []
            for i, chunk in enumerate(chunks):
                task = self._fast_scan_chunk_worker(i, chunk, len(directories))
                tasks.append(task)
            
            # Wait for all workers to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            total_files = len(root_files)
            total_size = sum(item['size'] for item in root_files)
            errors = 0
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"❌ [FAST_PARALLEL_SCAN] Worker {i} failed: {result}")
                    errors += 1
                else:
                    total_files += len(result.get('files', []))
                    total_size += result.get('total_size', 0)
                    print(f"✅ [FAST_PARALLEL_SCAN] Worker {i} completed: {len(result.get('files', []))} files, {self._format_bytes(result.get('total_size', 0))}")
            
            total_size_formatted = self._format_bytes(total_size)
            
            print(f"✅ [FAST_PARALLEL_SCAN] Scan completed! Total: {total_files} files, {total_size_formatted}")
            
            return {
                'status': 'completed',
                'total_files': total_files,
                'total_size': total_size,
                'total_size_formatted': total_size_formatted,
                'progress': 100,
                'message': f'Found {total_files} files using fast parallel scanning',
                'parallel_mode': True,
                'workers_used': 5,
                'errors': errors
            }
            
        except Exception as e:
            print(f"❌ [FAST_PARALLEL_SCAN] Error during parallel scan: {e}")
            return {
                'status': 'error',
                'total_files': 0,
                'total_size': 0,
                'total_size_formatted': '0 B',
                'progress': 0,
                'message': f'Scan failed: {str(e)}',
                'parallel_mode': True,
                'workers_used': 5,
                'error': str(e)
            }

    async def _fast_scan_chunk_worker(self, worker_id: int, directories: list, total_dirs: int) -> dict:
        """
        Fast worker function for scanning a chunk of directories
        """
        try:
            print(f"[WORKER_{worker_id}] Scanning {len(directories)} directories...")
            worker_files = []
            worker_total_size = 0
            
            for directory in directories:
                # directories are already strings, not objects
                dir_path = directory if isinstance(directory, str) else str(directory)
                if not dir_path:
                    continue
                
                try:
                    # Scan this directory recursively using the proven method
                    dir_result = await self._scan_storage_recursive(dir_path, set())
                    dir_files = dir_result.get('files', [])
                    dir_size = dir_result.get('total_size', 0)
                    
                    worker_files.extend(dir_files)
                    worker_total_size += dir_size
                    
                    print(f"[WORKER_{worker_id}] Scanned {dir_path}: {len(dir_files)} files, {self._format_bytes(dir_size)}")
                    
                    # Minimal delay to avoid overwhelming the server
                    await asyncio.sleep(0.02)
                    
                except Exception as e:
                    print(f"[WORKER_{worker_id}] Error scanning {dir_path}: {e}")
                    continue
            
            print(f"[WORKER_{worker_id}] ✅ Completed: {len(worker_files)} files, {self._format_bytes(worker_total_size)}")
            return {
                "files": worker_files,
                "total_size": worker_total_size
            }
            
        except Exception as e:
            print(f"❌ [WORKER_{worker_id}] Worker failed: {e}")
            raise e

    def _format_bytes(self, bytes_value: int) -> str:
        """Helper method to format bytes into human readable format"""
        if bytes_value == 0:
            return "0 B"
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes_value >= k and i < len(sizes) - 1:
            bytes_value /= k
            i += 1
        return f"{bytes_value:.2f} {sizes[i]}"
