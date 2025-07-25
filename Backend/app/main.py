# FILE: Backend/app/main.py

import httpx
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
    # ADD AT START
    async with upload_semaphore:  # Wait for available upload slot
        await websocket.accept()
        file_doc = db.files.find_one({"_id": file_id})
        if not file_doc: await websocket.close(code=1008, reason="File ID not found"); return
        if not gdrive_url: await websocket.close(code=1008, reason="gdrive_url query parameter is missing."); return
        
        # Mark upload as started
        db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
        
        total_size = file_doc.get("size_bytes", 0)
        
        upload_cancelled = False
        bytes_sent = 0  # Move outside httpx block for proper scope
        try:
            # Simplified upload proxy logic
            async with httpx.AsyncClient(timeout=None) as client:
                while bytes_sent < total_size:
                    try:
                        message = await websocket.receive()
                        chunk = message.get("bytes")
                        if not chunk: continue
                    except Exception as e:
                        # WebSocket disconnection - if upload incomplete, treat as cancellation
                        if bytes_sent < total_size:
                            # Upload incomplete = user cancellation
                            print(f"[UPLOAD_CANCEL] File: {file_id} | User cancelled upload | Reason: {e or 'WebSocket closed'}")
                            print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%)")
                            upload_cancelled = True
                        else:
                            # Upload complete but still got exception
                            print(f"[UPLOAD_ERROR] File: {file_id} | Connection error after completion | Reason: {e}")
                        break
                    
                    start_byte = bytes_sent
                    end_byte = bytes_sent + len(chunk) - 1
                    headers = {'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'}
                    response = await client.put(gdrive_url, content=chunk, headers=headers)
                    
                    if response.status_code not in [200, 201, 308]:
                        raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

                    bytes_sent += len(chunk)
                    await websocket.send_json({"type": "progress", "value": int((bytes_sent / total_size) * 100)})

            # Only complete the upload if it wasn't cancelled
            if not upload_cancelled:
                # Get final GDrive ID from the last response
                gdrive_response_data = response.json() if 'response' in locals() and response else {}
                gdrive_id = gdrive_response_data.get('id')
                if not gdrive_id and total_size > 0:
                    raise Exception("Upload to GDrive succeeded, but no file ID was returned.")

                db.files.update_one({"_id": file_id}, {"$set": {"gdrive_id": gdrive_id, "status": UploadStatus.COMPLETED, "storage_location": StorageLocation.GDRIVE }})
                
                # UPDATE USER STORAGE USAGE
                if file_doc.get("owner_id"):
                    db.users.update_one(
                        {"_id": file_doc["owner_id"]},
                        {"$inc": {"storage_used_bytes": file_doc["size_bytes"]}}
                    )
                
                await websocket.send_json({"type": "success", "value": f"/api/v1/download/stream/{file_id}"})
                
                print(f"[MAIN] Triggering silent Hetzner backup for file_id: {file_id}")
                asyncio.create_task(run_controlled_backup(file_id))
                print(f"[UPLOAD_SUCCESS] File {file_id} upload completed successfully")
            else:
                print(f"[UPLOAD_CANCEL] Skipping upload completion logic - upload was cancelled")

        except Exception as e:
            print(f"!!! [{file_id}] Upload proxy failed: {e}")
            # Only send error message if WebSocket is still connected
            try:
                await websocket.send_json({"type": "error", "value": str(e)})
            except:
                print(f"[{file_id}] Could not send error message, WebSocket disconnected")
            
            # Robust cancellation detection: check both flag and upload completeness
            if upload_cancelled or (bytes_sent < total_size):
                # Either explicitly cancelled or upload incomplete = user cancellation
                if not upload_cancelled:
                    print(f"[UPLOAD_CANCEL] File: {file_id} | User cancelled upload (outer handler) | Reason: {e or 'WebSocket disconnected'}")
                    print(f"[UPLOAD_CANCEL] Progress: {bytes_sent}/{total_size} bytes ({int((bytes_sent/total_size)*100) if total_size > 0 else 0}%)")
                print(f"[UPLOAD_CANCEL] Updating database status to 'cancelled' for file: {file_id}")
                db.files.update_one({"_id": file_id}, {"$set": {"status": "cancelled"}})
                print(f"[UPLOAD_CANCEL] File {file_id} successfully marked as cancelled in database")
            else:
                print(f"[UPLOAD_ERROR] Updating database status to 'failed' for file: {file_id}")
                db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
        finally:
            # Release rate limit for anonymous uploads
            if file_doc and file_doc.get("owner_id") is None:  # Anonymous upload
                ip = websocket.client.host
                from app.services.rate_limiter import rate_limiter
                await rate_limiter.release_upload(ip)
                if upload_cancelled:
                    print(f"[UPLOAD_CANCEL] Released rate limit for IP: {ip} after cancellation")
            
            # Log final cleanup
            if upload_cancelled:
                print(f"[UPLOAD_CANCEL] Complete cleanup finished for file: {file_id}")
            
            # Close WebSocket safely (avoid double close)
            try:
                if websocket.client_state.name != 'DISCONNECTED':
                    await websocket.close()
            except Exception as close_error:
                print(f"[DEBUG] WebSocket already closed or error closing: {close_error}")

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