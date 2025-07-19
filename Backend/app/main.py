# FILE: Backend/app/main.py (FINAL CORRECTED VERSION)

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List

# --- Local Imports ---
from app.api.v1.routes_upload import router as http_upload_router
from app.api.v1 import routes_auth, routes_download, routes_batch_upload
from app.db.mongodb import db
from app.models.file import UploadStatus, StorageLocation
from app.core.config import settings
from app.ws_manager import manager

# ===================================================================
# 1. DEFINE THE CONNECTION MANAGER FOR ADMINS
# This class will live directly inside main.py for simplicity.
# ===================================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print("Admin client connected.")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print("Admin client disconnected.")

    async def broadcast(self, data: dict):
        # This function sends structured JSON to all connected admins.
        for connection in self.active_connections:
            await connection.send_json(data)

# Create a single, global instance for our app to use.
manager = ConnectionManager()
# ===================================================================

# --- Create the FastAPI application instance ---
app = FastAPI(title="File Transfer Service")

origins = [
    "http://localhost:4200",
    "http://135.148.33.247",
    "https://teletransfer.vercel.app",
    "https://*.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================================================================
# 2. DEFINE THE ADMIN WEBSOCKET ENDPOINT
# This is the "phone line" that the admin panel connects to.
# ===================================================================
@app.websocket("/ws_admin")
async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
    if token != settings.ADMIN_WEBSOCKET_TOKEN:
        await websocket.close(code=1008, reason="Invalid admin token")
        return
    
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
# ===================================================================

@app.websocket("/ws_api/upload/{file_id}")
async def websocket_upload_proxy(
    websocket: WebSocket,
    file_id: str,
    gdrive_url: str
):
    await websocket.accept()
    
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        await websocket.close(code=1008, reason="File ID not found")
        return

    if not gdrive_url:
        await websocket.close(code=1008, reason="gdrive_url query parameter is missing.")
        return

    total_size = file_doc.get("size_bytes", 0)
    bytes_sent = 0

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
            # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
            await manager.broadcast({"type": "EVENT", "message": f"Upload started for file '{file_doc.get('filename')}' (ID: {file_id})"})
            
            while True:
                message = await websocket.receive()
                chunk = message.get("bytes")
                
                if not chunk:
                    if "text" in message and message["text"] == "DONE":
                        break
                    continue
                
                start_byte = bytes_sent
                end_byte = bytes_sent + len(chunk) - 1
                headers = {
                    'Content-Length': str(len(chunk)),
                    'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'
                }
                
                response = await client.put(gdrive_url, content=chunk, headers=headers)
                
                if response.status_code not in [200, 201, 308]:
                    raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

                bytes_sent += len(chunk)
                percentage = int((bytes_sent / total_size) * 100)
                await websocket.send_json({"type": "progress", "value": percentage})
            
            # Final response check
            if response.status_code not in [200, 201]:
                 raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
            gdrive_response_data = response.json()
            gdrive_id = gdrive_response_data.get('id')
            if not gdrive_id:
                raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

            db.files.update_one(
                {"_id": file_id},
                {"$set": {
                    "gdrive_id": gdrive_id,
                    "status": UploadStatus.COMPLETED,
                    "storage_location": StorageLocation.GDRIVE 
                }}
            )

            download_path = f"/api/v1/download/stream/{file_id}"
            await websocket.send_json({"type": "success", "value": download_path})
            # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
            await manager.broadcast({"type": "SUCCESS", "message": f"File '{file_doc.get('filename')}' uploaded successfully. Link created."})

        except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
            print(f"!!! [{file_id}] Upload proxy failed: {e}")
            db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
            # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
            await manager.broadcast({"type": "ERROR", "message": f"Upload FAILED for file '{file_doc.get('filename')}'. Reason: {e}"})
            try:
                 await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
            except RuntimeError:
                pass
        finally:
            if websocket.client_state != "DISCONNECTED":
                await websocket.close()

# --- Simplified Health Check ---
@app.get("/healthz", tags=["Health Check"])
async def health_check():
    return {"status": "ok"}

# --- Include all other routers ---
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the File Transfer API"}
