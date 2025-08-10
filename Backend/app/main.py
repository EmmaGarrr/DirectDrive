# FILE: Backend/app/main.py

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import asyncio

from app.api.v1.routes_upload import router as http_upload_router
from app.api.v1 import routes_auth, routes_download, routes_batch_upload
from app.db.mongodb import db
from app.models.file import UploadStatus, StorageLocation
from app.core.config import settings
# Use the new, stable backup service
from app.services import backup_service
from app.services.google_drive_account_service import GoogleDriveAccountService
from app.services.google_drive_service import gdrive_pool_manager
# Priority queue middleware
from app.middleware.priority_middleware import PriorityMiddleware

# Strict concurrency limiter for server stability
BACKUP_TASK_SEMAPHORE = asyncio.Semaphore(1)

# --- The rest of the main.py file is largely the same ---
class ConnectionManager:
    # ...
    def __init__(self): 
        self.active_connections: List[WebSocket] = []
        # Start background task for periodic updates
        asyncio.create_task(self.periodic_updates())
        
    async def connect(self, websocket: WebSocket): 
        await websocket.accept()
        self.active_connections.append(websocket)
        
    def disconnect(self, websocket: WebSocket): 
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            
    async def broadcast(self, data: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                print(f"[WebSocket] Failed to send to connection: {e}")
                disconnected.append(connection)
        
        # Remove disconnected connections
        for conn in disconnected:
            self.disconnect(conn)
    
    async def periodic_updates(self):
        """Send periodic system updates to connected admin clients"""
        while True:
            try:
                await asyncio.sleep(30)  # Send update every 30 seconds
                if self.active_connections:
                    import time
                    from app.db.mongodb import db
                    
                    # Get basic system stats
                    total_files = db.files.count_documents({})
                    total_users = db.users.count_documents({})
                    
                    await self.broadcast({
                        "type": "system_update",
                        "message": f"[System] {time.strftime('%H:%M:%S')} - Files: {total_files}, Users: {total_users}, Connections: {len(self.active_connections)}"
                    })
            except Exception as e:
                print(f"[WebSocket] Periodic update error: {e}")
                await asyncio.sleep(60)  # Wait longer on error

manager = ConnectionManager()
app = FastAPI(title="File Transfer Service")
origins = ["http://localhost:4200", "http://135.148.33.247", "https://teletransfer.vercel.app", "https://*.vercel.app"]

# Add priority middleware first (before CORS)
app.add_middleware(PriorityMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Startup hooks for storage account health and pool sync ---
@app.on_event("startup")
async def startup_storage_management():
    try:
        # Ensure accounts collection exists, migrate from env on first run, and sync
        await GoogleDriveAccountService.initialize_service()
        # Prefer DB-backed pool over env; reload once at startup
        await gdrive_pool_manager.reload_from_db()  # type: ignore
        print("[MAIN] Google Drive account service initialized and pool reloaded from DB")
    except Exception as e:
        print(f"[MAIN] Startup storage management init failed: {e}")

    # Periodically refresh quota/health to keep gating accurate
    async def periodic_account_health_refresh():
        while True:
            try:
                await GoogleDriveAccountService.update_all_accounts_quota()
            except Exception as e:
                print(f"[MAIN] Periodic account quota refresh failed: {e}")
            # Refresh every 15 minutes
            await asyncio.sleep(900)

    try:
        asyncio.create_task(periodic_account_health_refresh())
        print("[MAIN] Scheduled periodic account health refresh task")
    except Exception as e:
        print(f"[MAIN] Failed to schedule periodic account health refresh: {e}")

@app.websocket("/ws_admin")
async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
    """Admin WebSocket endpoint with JWT authentication"""
    from app.services.admin_auth_service import get_current_admin
    from app.models.admin import AdminUserInDB
    from jose import JWTError, jwt
    
    # Validate JWT token
    try:
        if not token:
            await websocket.close(code=1008, reason="No token provided")
            return
            
        # Decode and validate JWT token
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        is_admin: bool = payload.get("is_admin", False)
        
        if email is None or not is_admin:
            await websocket.close(code=1008, reason="Invalid admin token")
            return
            
        # Verify admin user exists in database
        from app.db.mongodb import db
        user = db.users.find_one({"email": email})
        if not user or user.get("role") not in ["admin", "superadmin"]:
            await websocket.close(code=1008, reason="Admin user not found or insufficient permissions")
            return
            
        # Create admin object for logging
        admin = AdminUserInDB(**user)
        
    except JWTError as e:
        await websocket.close(code=1008, reason="Invalid JWT token")
        return
    except Exception as e:
        await websocket.close(code=1008, reason="Authentication failed")
        return
    
    # Connection successful
    await manager.connect(websocket)
    print(f"[WebSocket] Admin connected: {admin.email} (Role: {admin.role})")
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "system",
            "message": f"[WebSocket] Connected as {admin.role}: {admin.email}"
        })
        
        # Send initial system status
        import time
        await websocket.send_json({
            "type": "status",
            "message": f"[System] Admin panel connected at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        })
        
        # Keep connection alive and handle messages
        while True:
            try:
                message = await websocket.receive_text()
                # Echo received messages and broadcast to demonstrate real-time capability
                response_msg = f"[{admin.role.upper()}] {admin.email}: {message}"
                
                # Broadcast to all connected admin clients
                await manager.broadcast({
                    "type": "admin_message",
                    "message": response_msg
                })
                
            except Exception as e:
                print(f"[WebSocket] Message handling error: {e}")
                break
                
    except WebSocketDisconnect:
        print(f"[WebSocket] Admin disconnected: {admin.email}")
    except Exception as e:
        print(f"[WebSocket] Connection error: {e}")
    finally:
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
    await websocket.accept()
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc: await websocket.close(code=1008, reason="File ID not found"); return
    if not gdrive_url: await websocket.close(code=1008, reason="gdrive_url query parameter is missing."); return
    
    total_size = file_doc.get("size_bytes", 0)
    
    try:
        # Simplified upload proxy logic
        async with httpx.AsyncClient(timeout=None) as client:
            bytes_sent = 0
            while bytes_sent < total_size:
                message = await websocket.receive()
                chunk = message.get("bytes")
                if not chunk: continue
                
                start_byte = bytes_sent
                end_byte = bytes_sent + len(chunk) - 1
                headers = {'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'}
                response = await client.put(gdrive_url, content=chunk, headers=headers)
                
                if response.status_code not in [200, 201, 308]:
                    raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

                bytes_sent += len(chunk)
                await websocket.send_json({"type": "progress", "value": int((bytes_sent / total_size) * 100)})

        # Get final GDrive ID from the last response
        gdrive_response_data = response.json() if 'response' in locals() and response else {}
        gdrive_id = gdrive_response_data.get('id')
        if not gdrive_id and total_size > 0:
            raise Exception("Upload to GDrive succeeded, but no file ID was returned.")

        db.files.update_one({"_id": file_id}, {"$set": {"gdrive_id": gdrive_id, "status": UploadStatus.COMPLETED, "storage_location": StorageLocation.GDRIVE }})
        await websocket.send_json({"type": "success", "value": f"/api/v1/download/stream/{file_id}"})

        # Update Google Drive account stats promptly after successful upload
        try:
            updated_doc = db.files.find_one({"_id": file_id})
            if updated_doc and updated_doc.get("gdrive_account_id"):
                from app.services.google_drive_account_service import GoogleDriveAccountService
                await GoogleDriveAccountService.update_account_after_file_operation(
                    updated_doc.get("gdrive_account_id"),
                    updated_doc.get("size_bytes", 0)
                )
        except Exception as e:
            print(f"[MAIN] Failed to update account stats after upload {file_id}: {e}")
        
        print(f"[MAIN] Triggering silent Hetzner backup for file_id: {file_id}")
        asyncio.create_task(run_controlled_backup(file_id))

    except Exception as e:
        print(f"!!! [{file_id}] Upload proxy failed: {e}")
        db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
        try: await websocket.send_json({"type": "error", "value": "Upload failed."})
        except RuntimeError: pass
    finally:
        if websocket.client_state != "DISCONNECTED": await websocket.close()

# Include other routers
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

# Import and include admin routes
from app.api.v1 import routes_admin_auth, routes_admin_users, routes_admin_files, routes_admin_storage, routes_admin_monitoring, routes_admin_config, routes_admin_notifications, routes_admin_reports
app.include_router(routes_admin_auth.router, prefix="/api/v1/admin/auth", tags=["Admin Authentication"])
app.include_router(routes_admin_users.router, prefix="/api/v1/admin", tags=["Admin User Management"])
app.include_router(routes_admin_files.router, prefix="/api/v1/admin", tags=["Admin File Management"])
app.include_router(routes_admin_storage.router, prefix="/api/v1/admin", tags=["Admin Storage Management"])
app.include_router(routes_admin_monitoring.router, prefix="/api/v1/admin", tags=["Admin System Monitoring"])
app.include_router(routes_admin_config.router, prefix="/api/v1/admin", tags=["Admin Configuration"])
app.include_router(routes_admin_notifications.router, prefix="/api/v1/admin", tags=["Admin Notifications"])
app.include_router(routes_admin_reports.router, prefix="/api/v1/admin", tags=["Admin Reports & Export"])
@app.get("/")
def read_root(): return {"message": "Welcome to the File Transfer API"}