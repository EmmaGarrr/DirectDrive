# FILE: Backend/app/main.py

import httpx
import sys
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from typing import List
import asyncio

from app.api.v1.routes_upload import router as http_upload_router
from app.api.v1 import routes_auth, routes_download, routes_batch_upload
from app.db.mongodb import db
from app.models.file import UploadStatus, StorageLocation
from app.core.config import settings
# Use the new, stable backup service
from app.services import backup_service

# Increased concurrency limiter for better throughput
# RESOURCE PROTECTION FOR 2-CORE SERVER
MAX_CONCURRENT_UPLOADS = 20  # Max 20 uploads globally
MAX_CONCURRENT_DOWNLOADS = 30  # Max 30 downloads globally
BACKUP_TASK_SEMAPHORE = asyncio.Semaphore(3)  # CHANGE from 10 to 3

upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# --- The rest of the main.py file is largely the same ---
class ConnectionManager:
    # ...
    def __init__(self): self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket): await websocket.accept(); self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket): self.active_connections.remove(websocket)
    async def broadcast(self, data: dict):
        for connection in self.active_connections: await connection.send_json(data)

manager = ConnectionManager()
app = FastAPI(title="File Transfer Service")

# ADD INDEX CREATION AND CLEANUP TASK TO STARTUP
from app.db.indexes import create_indexes
from app.tasks.cleanup_task import cleanup_orphaned_uploads

# Global semaphores for resource protection
upload_semaphore = asyncio.Semaphore(20)  # Max 20 concurrent uploads
download_semaphore = asyncio.Semaphore(30)  # Max 30 concurrent downloads
backup_semaphore = asyncio.Semaphore(3)   # Max 3 concurrent backup operations

async def run_periodic_cleanup():
    """Run the cleanup task periodically to free up disk space"""
    while True:
        try:
            # Run cleanup task every 2 hours
            await cleanup_orphaned_uploads()
            print("[CLEANUP] Completed orphaned uploads cleanup task")
        except Exception as e:
            print(f"[CLEANUP] Error during cleanup task: {e}")
        
        # Wait for 2 hours before running again
        await asyncio.sleep(7200)  # 2 hours = 7200 seconds

@app.on_event("startup")
async def startup_event():
    # Create MongoDB indexes
    create_indexes()
    
    # Start the periodic cleanup task
    asyncio.create_task(run_periodic_cleanup())

# Import request filter middleware
from app.middleware.request_filter import RequestFilterMiddleware

origins = ["http://localhost:4200", "http://135.148.33.247", "https://teletransfer.vercel.app", "https://*.vercel.app"]

# Add request filter middleware first (executes first)
app.add_middleware(RequestFilterMiddleware)

# Add CORS middleware
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.websocket("/ws_admin")
async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
    # ... admin websocket logic ...
    if token != settings.ADMIN_WEBSOCKET_TOKEN:
        await websocket.close(code=1008, reason="Invalid admin token"); return
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def run_controlled_backup(file_id: str):
    """Wrapper to run the backup task with the semaphore."""
    async with BACKUP_TASK_SEMAPHORE:
        print(f"[MAIN][Semaphore Acquired] Starting controlled backup for {file_id}")
        # Call the new backup service
        await backup_service.transfer_gdrive_to_hetzner(file_id)
    print(f"[MAIN][Semaphore Released] Finished controlled backup for {file_id}")

@app.websocket("/ws_api/upload/{file_id}")
async def websocket_upload_proxy(websocket: WebSocket, file_id: str, gdrive_url: str):
    # IMMEDIATE LOGGING - Before semaphore acquisition
    client_ip = websocket.client.host if websocket.client else "unknown"
    print(f"[UPLOAD_START] File: {file_id} | Client: {client_ip} | WebSocket connection attempt")
    sys.stdout.flush()  # Force immediate log output
    
    # Pre-validate file and gdrive_url before taking semaphore slot
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        print(f"[UPLOAD_ERROR] File: {file_id} | File ID not found in database")
        sys.stdout.flush()
        await websocket.close(code=1008, reason="File ID not found")
        return
        
    if not gdrive_url:
        print(f"[UPLOAD_ERROR] File: {file_id} | Missing gdrive_url parameter")
        sys.stdout.flush()
        await websocket.close(code=1008, reason="gdrive_url query parameter is missing.")
        return
    
    print(f"[UPLOAD_START] File: {file_id} | Google Drive URL received | Size: {file_doc.get('size_bytes', 0)} bytes")
    sys.stdout.flush()
    
    # NOW acquire semaphore for actual upload processing
    print(f"[UPLOAD_START] File: {file_id} | Waiting for upload slot (semaphore)")
    sys.stdout.flush()
    
    async with upload_semaphore:  # Wait for available upload slot
        print(f"[UPLOAD_START] File: {file_id} | Upload slot acquired, accepting WebSocket connection")
        sys.stdout.flush()
        
        await websocket.accept()
        
        print(f"[UPLOAD_START] File: {file_id} | WebSocket accepted, starting upload process")
        sys.stdout.flush()
        
        # Mark upload as started
        db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
        print(f"[UPLOAD_START] File: {file_id} | Database status updated to UPLOADING")
        sys.stdout.flush()
        
        total_size = file_doc.get("size_bytes", 0)
        
        upload_cancelled = False
        bytes_sent = 0  # Move outside httpx block for proper scope
        chunk_count = 0
        cancel_requested = False  # Flag for graceful cancellation
        
        print(f"[UPLOAD_PROGRESS] File: {file_id} | Starting upload loop | Total size: {total_size} bytes")
        sys.stdout.flush()
        
        try:
            # Simplified upload proxy logic
            async with httpx.AsyncClient(timeout=None) as client:
                print(f"[UPLOAD_PROGRESS] File: {file_id} | HTTP client initialized, ready to receive chunks")
                sys.stdout.flush()
                
                while bytes_sent < total_size and not cancel_requested:
                    try:
                        # Shorter timeout for faster cancel detection
                        message = await asyncio.wait_for(websocket.receive(), timeout=2.0)
                        
                        # Check for cancellation message first
                        if message.get("type") == "cancel":
                            cancel_requested = True
                            upload_cancelled = True
                            print(f"[UPLOAD_CANCEL] File: {file_id} | Cancel request received from client | Immediate stop")
                            print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%) | Chunks processed: {chunk_count}")
                            sys.stdout.flush()
                            
                            # Send acknowledgment to frontend
                            try:
                                await websocket.send_json({"type": "cancel_ack", "message": "Upload cancelled successfully"})
                                print(f"[UPLOAD_CANCEL] File: {file_id} | Cancel acknowledgment sent to client")
                                sys.stdout.flush()
                            except Exception as ack_error:
                                print(f"[UPLOAD_CANCEL] File: {file_id} | Could not send cancel ACK: {ack_error}")
                                sys.stdout.flush()
                            
                            break
                        
                        chunk = message.get("bytes")
                        if not chunk: 
                            print(f"[UPLOAD_DEBUG] File: {file_id} | Received empty chunk, continuing")
                            continue
                        
                        chunk_count += 1
                        if chunk_count % 50 == 0:  # Log every 50 chunks to avoid spam
                            print(f"[UPLOAD_PROGRESS] File: {file_id} | Chunk #{chunk_count} | Progress: {bytes_sent}/{total_size} bytes")
                            sys.stdout.flush()
                            
                    except asyncio.TimeoutError:
                        # Check if WebSocket is still connected
                        if websocket.client_state.name == 'DISCONNECTED':
                            print(f"[UPLOAD_CANCEL] File: {file_id} | WebSocket disconnected (timeout detection) | User cancelled upload")
                            print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%) | Chunks processed: {chunk_count}")
                            sys.stdout.flush()
                            upload_cancelled = True
                            break
                        else:
                            # Still connected, continue waiting for chunks
                            continue
                            
                    except Exception as e:
                        # WebSocket disconnection - if upload incomplete, treat as cancellation
                        error_type = type(e).__name__
                        print(f"[UPLOAD_CANCEL] File: {file_id} | WebSocket error detected | Error: {error_type}: {e}")
                        
                        if bytes_sent < total_size:
                            # Upload incomplete = user cancellation
                            print(f"[UPLOAD_CANCEL] File: {file_id} | User cancelled upload | Reason: {error_type}")
                            print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%) | Chunks processed: {chunk_count}")
                            sys.stdout.flush()
                            upload_cancelled = True
                        else:
                            # Upload complete but still got exception
                            print(f"[UPLOAD_ERROR] File: {file_id} | Connection error after completion | Reason: {error_type}: {e}")
                            sys.stdout.flush()
                        break
                    
                    start_byte = bytes_sent
                    end_byte = bytes_sent + len(chunk) - 1
                    headers = {'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'}
                    
                    # Upload chunk to Google Drive
                    response = await client.put(gdrive_url, content=chunk, headers=headers)
                    
                    if response.status_code not in [200, 201, 308]:
                        error_msg = f"Google Drive API Error: {response.text}"
                        print(f"[UPLOAD_ERROR] File: {file_id} | GDrive API error | Status: {response.status_code} | Error: {error_msg}")
                        sys.stdout.flush()
                        raise HTTPException(status_code=response.status_code, detail=error_msg)

                    bytes_sent += len(chunk)
                    progress_percent = int((bytes_sent / total_size) * 100)
                    await websocket.send_json({"type": "progress", "value": progress_percent})
                    
                    # Log progress milestones
                    if progress_percent % 25 == 0 and chunk_count % 50 == 0:
                        print(f"[UPLOAD_PROGRESS] File: {file_id} | {progress_percent}% complete | {bytes_sent}/{total_size} bytes")
                        sys.stdout.flush()

            # Only complete the upload if it wasn't cancelled
            if not upload_cancelled:
                print(f"[UPLOAD_SUCCESS] File: {file_id} | Upload completed | Processing final steps")
                sys.stdout.flush()
                
                # Get final GDrive ID from the last response
                gdrive_response_data = response.json() if 'response' in locals() and response else {}
                gdrive_id = gdrive_response_data.get('id')
                if not gdrive_id and total_size > 0:
                    error_msg = "Upload to GDrive succeeded, but no file ID was returned."
                    print(f"[UPLOAD_ERROR] File: {file_id} | {error_msg}")
                    sys.stdout.flush()
                    raise Exception(error_msg)

                print(f"[UPLOAD_SUCCESS] File: {file_id} | Received GDrive ID: {gdrive_id} | Updating database")
                sys.stdout.flush()
                
                db.files.update_one({"_id": file_id}, {"$set": {"gdrive_id": gdrive_id, "status": UploadStatus.COMPLETED, "storage_location": StorageLocation.GDRIVE }})
                
                # UPDATE USER STORAGE USAGE
                if file_doc.get("owner_id"):
                    print(f"[UPLOAD_SUCCESS] File: {file_id} | Updating user storage usage for owner: {file_doc['owner_id']}")
                    sys.stdout.flush()
                    db.users.update_one(
                        {"_id": file_doc["owner_id"]},
                        {"$inc": {"storage_used_bytes": file_doc["size_bytes"]}}
                    )
                
                await websocket.send_json({"type": "success", "value": f"/api/v1/download/stream/{file_id}"})
                
                print(f"[UPLOAD_SUCCESS] File: {file_id} | Success message sent to client | Triggering backup")
                sys.stdout.flush()
                
                asyncio.create_task(run_controlled_backup(file_id))
                print(f"[UPLOAD_SUCCESS] File: {file_id} | Upload completed successfully | Total: {bytes_sent}/{total_size} bytes | Chunks: {chunk_count}")
                sys.stdout.flush()
            else:
                print(f"[UPLOAD_CANCEL] File: {file_id} | Skipping upload completion logic - upload was cancelled")
                sys.stdout.flush()

        except Exception as e:
            print(f"[UPLOAD_ERROR] File: {file_id} | Upload proxy failed | Error: {type(e).__name__}: {e}")
            sys.stdout.flush()
            
            # Only send error message if WebSocket is still connected
            try:
                await websocket.send_json({"type": "error", "value": str(e)})
                print(f"[UPLOAD_ERROR] File: {file_id} | Error message sent to client")
                sys.stdout.flush()
            except Exception as send_error:
                print(f"[UPLOAD_ERROR] File: {file_id} | Could not send error message, WebSocket disconnected | Send error: {send_error}")
                sys.stdout.flush()
            
            # Robust cancellation detection: check both flag and upload completeness
            if upload_cancelled or (bytes_sent < total_size):
                # Either explicitly cancelled or upload incomplete = user cancellation
                if not upload_cancelled:
                    print(f"[UPLOAD_CANCEL] File: {file_id} | User cancelled upload (outer handler) | Reason: {e or 'WebSocket disconnected'}")
                    print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%) | Chunks: {chunk_count}")
                    sys.stdout.flush()
                
                print(f"[UPLOAD_CANCEL] File: {file_id} | Updating database status to 'cancelled'")
                sys.stdout.flush()
                db.files.update_one({"_id": file_id}, {"$set": {"status": "cancelled"}})
                print(f"[UPLOAD_CANCEL] File: {file_id} | Successfully marked as cancelled in database")
                sys.stdout.flush()
            else:
                print(f"[UPLOAD_ERROR] File: {file_id} | Upload failed after completion | Updating database status to 'failed'")
                sys.stdout.flush()
                db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
                print(f"[UPLOAD_ERROR] File: {file_id} | Successfully marked as failed in database")
                sys.stdout.flush()
        finally:
            print(f"[UPLOAD_CLEANUP] File: {file_id} | Starting cleanup process | Upload cancelled: {upload_cancelled} | Bytes sent: {bytes_sent}/{total_size}")
            sys.stdout.flush()
            
            # Release rate limit for anonymous uploads
            if file_doc and file_doc.get("owner_id") is None:  # Anonymous upload
                ip = websocket.client.host if websocket.client else "unknown"
                print(f"[UPLOAD_CLEANUP] File: {file_id} | Releasing rate limit for anonymous IP: {ip}")
                sys.stdout.flush()
                
                from app.services.rate_limiter import rate_limiter
                await rate_limiter.release_upload(ip)
                
                if upload_cancelled:
                    print(f"[UPLOAD_CANCEL] File: {file_id} | Rate limit released for IP: {ip} after cancellation")
                    sys.stdout.flush()
                else:
                    print(f"[UPLOAD_CLEANUP] File: {file_id} | Rate limit released for IP: {ip}")
                    sys.stdout.flush()
            
            # Log final cleanup status
            if upload_cancelled:
                print(f"[UPLOAD_CANCEL] File: {file_id} | Complete cleanup finished | Final status: cancelled")
                sys.stdout.flush()
            else:
                print(f"[UPLOAD_CLEANUP] File: {file_id} | Complete cleanup finished | Final status: {bytes_sent >= total_size and 'success' or 'incomplete'}")
                sys.stdout.flush()
            
            # Close WebSocket safely (avoid double close)
            try:
                if websocket.client_state.name != 'DISCONNECTED':
                    print(f"[UPLOAD_CLEANUP] File: {file_id} | Closing WebSocket connection")
                    sys.stdout.flush()
                    await websocket.close()
                else:
                    print(f"[UPLOAD_CLEANUP] File: {file_id} | WebSocket already disconnected")
                    sys.stdout.flush()
            except Exception as close_error:
                print(f"[UPLOAD_CLEANUP] File: {file_id} | WebSocket close error (expected for cancelled uploads): {close_error}")
                sys.stdout.flush()

# Include other routers
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])
@app.get("/")
def read_root():
    return {"message": "File Transfer Service API"}

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring and load balancers"""
    return {"status": "healthy", "service": "DirectDrive API"}

@app.get("/robots.txt")
def robots_txt():
    """Robots.txt to reduce bot crawling"""
    return PlainTextResponse("User-agent: *\nDisallow: /")