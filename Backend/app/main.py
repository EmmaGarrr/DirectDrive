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

# Strict concurrency limiter for server stability
BACKUP_TASK_SEMAPHORE = asyncio.Semaphore(1)

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
origins = ["http://localhost:4200", "http://135.148.33.247", "https://teletransfer.vercel.app", "https://*.vercel.app"]
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
@app.get("/")
def read_root(): return {"message": "Welcome to the File Transfer API"}