# # # # FILE: Backend/app/main.py (FINAL CORRECTED VERSION)

# # # import httpx
# # # from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
# # # from fastapi.middleware.cors import CORSMiddleware
# # # from typing import List

# # # # --- Local Imports ---
# # # from app.api.v1.routes_upload import router as http_upload_router
# # # from app.api.v1 import routes_auth, routes_download, routes_batch_upload
# # # from app.db.mongodb import db
# # # from app.models.file import UploadStatus, StorageLocation
# # # from app.core.config import settings
# # # from app.ws_manager import manager

# # # # ===================================================================
# # # # 1. DEFINE THE CONNECTION MANAGER FOR ADMINS
# # # # This class will live directly inside main.py for simplicity.
# # # # ===================================================================
# # # class ConnectionManager:
# # #     def __init__(self):
# # #         self.active_connections: List[WebSocket] = []

# # #     async def connect(self, websocket: WebSocket):
# # #         await websocket.accept()
# # #         self.active_connections.append(websocket)
# # #         print("Admin client connected.")

# # #     def disconnect(self, websocket: WebSocket):
# # #         self.active_connections.remove(websocket)
# # #         print("Admin client disconnected.")

# # #     async def broadcast(self, data: dict):
# # #         # This function sends structured JSON to all connected admins.
# # #         for connection in self.active_connections:
# # #             await connection.send_json(data)

# # # # Create a single, global instance for our app to use.
# # # manager = ConnectionManager()
# # # # ===================================================================

# # # # --- Create the FastAPI application instance ---
# # # app = FastAPI(title="File Transfer Service")

# # # origins = [
# # #     "http://localhost:4200",
# # #     "http://135.148.33.247",
# # #     "https://teletransfer.vercel.app",
# # #     "https://*.vercel.app"
# # # ]

# # # app.add_middleware(
# # #     CORSMiddleware,
# # #     allow_origins=origins,
# # #     allow_credentials=True,
# # #     allow_methods=["*"],
# # #     allow_headers=["*"],
# # # )

# # # # ===================================================================
# # # # 2. DEFINE THE ADMIN WEBSOCKET ENDPOINT
# # # # This is the "phone line" that the admin panel connects to.
# # # # ===================================================================
# # # @app.websocket("/ws_admin")
# # # async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
# # #     if token != settings.ADMIN_WEBSOCKET_TOKEN:
# # #         await websocket.close(code=1008, reason="Invalid admin token")
# # #         return
    
# # #     await manager.connect(websocket)
# # #     try:
# # #         while True:
# # #             # Keep connection alive.
# # #             await websocket.receive_text()
# # #     except WebSocketDisconnect:
# # #         manager.disconnect(websocket)
# # # # ===================================================================

# # # @app.websocket("/ws_api/upload/{file_id}")
# # # async def websocket_upload_proxy(
# # #     websocket: WebSocket,
# # #     file_id: str,
# # #     gdrive_url: str
# # # ):
# # #     await websocket.accept()
    
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         await websocket.close(code=1008, reason="File ID not found")
# # #         return

# # #     if not gdrive_url:
# # #         await websocket.close(code=1008, reason="gdrive_url query parameter is missing.")
# # #         return

# # #     total_size = file_doc.get("size_bytes", 0)
# # #     bytes_sent = 0

# # #     async with httpx.AsyncClient(timeout=None) as client:
# # #         try:
# # #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
# # #             # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
# # #             await manager.broadcast({"type": "EVENT", "message": f"Upload started for file '{file_doc.get('filename')}' (ID: {file_id})"})
            
# # #             while True:
# # #                 message = await websocket.receive()
# # #                 chunk = message.get("bytes")
                
# # #                 if not chunk:
# # #                     if "text" in message and message["text"] == "DONE":
# # #                         break
# # #                     continue
                
# # #                 start_byte = bytes_sent
# # #                 end_byte = bytes_sent + len(chunk) - 1
# # #                 headers = {
# # #                     'Content-Length': str(len(chunk)),
# # #                     'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'
# # #                 }
                
# # #                 response = await client.put(gdrive_url, content=chunk, headers=headers)
                
# # #                 if response.status_code not in [200, 201, 308]:
# # #                     raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

# # #                 bytes_sent += len(chunk)
# # #                 percentage = int((bytes_sent / total_size) * 100)
# # #                 await websocket.send_json({"type": "progress", "value": percentage})
            
# # #             # Final response check
# # #             if response.status_code not in [200, 201]:
# # #                  raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
# # #             gdrive_response_data = response.json()
# # #             gdrive_id = gdrive_response_data.get('id')
# # #             if not gdrive_id:
# # #                 raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

# # #             db.files.update_one(
# # #                 {"_id": file_id},
# # #                 {"$set": {
# # #                     "gdrive_id": gdrive_id,
# # #                     "status": UploadStatus.COMPLETED,
# # #                     "storage_location": StorageLocation.GDRIVE 
# # #                 }}
# # #             )

# # #             download_path = f"/api/v1/download/stream/{file_id}"
# # #             await websocket.send_json({"type": "success", "value": download_path})
# # #             # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
# # #             await manager.broadcast({"type": "SUCCESS", "message": f"File '{file_doc.get('filename')}' uploaded successfully. Link created."})

# # #         except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
# # #             print(f"!!! [{file_id}] Upload proxy failed: {e}")
# # #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
# # #             # --- 3. BROADCAST JSON MESSAGES USING THE NEW MANAGER ---
# # #             await manager.broadcast({"type": "ERROR", "message": f"Upload FAILED for file '{file_doc.get('filename')}'. Reason: {e}"})
# # #             try:
# # #                  await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
# # #             except RuntimeError:
# # #                 pass
# # #         finally:
# # #             if websocket.client_state != "DISCONNECTED":
# # #                 await websocket.close()

# # # # --- Simplified Health Check ---
# # # @app.get("/healthz", tags=["Health Check"])
# # # async def health_check():
# # #     return {"status": "ok"}

# # # # --- Include all other routers ---
# # # app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
# # # app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
# # # app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
# # # app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

# # # @app.get("/")
# # # def read_root():
# # #     return {"message": "Welcome to the File Transfer API"}





# # # FILE: Backend/app/main.py

# # import httpx
# # from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
# # from fastapi.middleware.cors import CORSMiddleware
# # from typing import List
# # import asyncio  # --- NEW: Import asyncio for background tasks ---

# # # --- Local Imports ---
# # from app.api.v1.routes_upload import router as http_upload_router
# # from app.api.v1 import routes_auth, routes_download, routes_batch_upload
# # from app.db.mongodb import db
# # from app.models.file import UploadStatus, StorageLocation
# # from app.core.config import settings
# # from app.services import hetzner_service  # --- NEW: Import the Hetzner service ---
# # # The ConnectionManager is no longer in ws_manager.py, so we keep the local version.

# # # ===================================================================
# # # CONNECTION MANAGER FOR ADMINS
# # # ===================================================================
# # class ConnectionManager:
# #     def __init__(self):
# #         self.active_connections: List[WebSocket] = []

# #     async def connect(self, websocket: WebSocket):
# #         await websocket.accept()
# #         self.active_connections.append(websocket)
# #         print("Admin client connected.")

# #     def disconnect(self, websocket: WebSocket):
# #         self.active_connections.remove(websocket)
# #         print("Admin client disconnected.")

# #     async def broadcast(self, data: dict):
# #         for connection in self.active_connections:
# #             await connection.send_json(data)

# # # Create a single, global instance for our app to use.
# # manager = ConnectionManager()
# # # ===================================================================

# # # --- Create the FastAPI application instance ---
# # app = FastAPI(title="File Transfer Service")

# # origins = [
# #     "http://localhost:4200",
# #     "http://135.148.33.247",
# #     "https://teletransfer.vercel.app",
# #     "https://*.vercel.app"
# # ]

# # app.add_middleware(
# #     CORSMiddleware,
# #     allow_origins=origins,
# #     allow_credentials=True,
# #     allow_methods=["*"],
# #     allow_headers=["*"],
# # )

# # # ===================================================================
# # # ADMIN WEBSOCKET ENDPOINT
# # # ===================================================================
# # @app.websocket("/ws_admin")
# # async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
# #     if token != settings.ADMIN_WEBSOCKET_TOKEN:
# #         await websocket.close(code=1008, reason="Invalid admin token")
# #         return
    
# #     await manager.connect(websocket)
# #     try:
# #         while True:
# #             await websocket.receive_text()
# #     except WebSocketDisconnect:
# #         manager.disconnect(websocket)
# # # ===================================================================

# # @app.websocket("/ws_api/upload/{file_id}")
# # async def websocket_upload_proxy(
# #     websocket: WebSocket,
# #     file_id: str,
# #     gdrive_url: str
# # ):
# #     await websocket.accept()
    
# #     file_doc = db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         await websocket.close(code=1008, reason="File ID not found")
# #         return

# #     if not gdrive_url:
# #         await websocket.close(code=1008, reason="gdrive_url query parameter is missing.")
# #         return

# #     total_size = file_doc.get("size_bytes", 0)
# #     bytes_sent = 0

# #     async with httpx.AsyncClient(timeout=None) as client:
# #         try:
# #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
# #             await manager.broadcast({"type": "EVENT", "message": f"Upload started for file '{file_doc.get('filename')}' (ID: {file_id})"})
            
# #             response = None # Initialize response to handle empty files
# #             while True:
# #                 message = await websocket.receive()
# #                 chunk = message.get("bytes")
                
# #                 if not chunk:
# #                     if "text" in message and message["text"] == "DONE":
# #                         break
# #                     continue
                
# #                 start_byte = bytes_sent
# #                 end_byte = bytes_sent + len(chunk) - 1
# #                 headers = {
# #                     'Content-Length': str(len(chunk)),
# #                     'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'
# #                 }
                
# #                 response = await client.put(gdrive_url, content=chunk, headers=headers)
                
# #                 if response.status_code not in [200, 201, 308]:
# #                     raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

# #                 bytes_sent += len(chunk)
# #                 percentage = int((bytes_sent / total_size) * 100) if total_size > 0 else 100
# #                 await websocket.send_json({"type": "progress", "value": percentage})
            
# #             # Final response check (handles empty files where the loop doesn't run)
# #             if total_size > 0 and response and response.status_code not in [200, 201]:
# #                  raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
# #             gdrive_response_data = response.json() if response else {}
# #             gdrive_id = gdrive_response_data.get('id')
# #             if not gdrive_id and total_size > 0:
# #                 raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

# #             db.files.update_one(
# #                 {"_id": file_id},
# #                 {"$set": {
# #                     "gdrive_id": gdrive_id,
# #                     "status": UploadStatus.COMPLETED,
# #                     "storage_location": StorageLocation.GDRIVE 
# #                 }}
# #             )

# #             download_path = f"/api/v1/download/stream/{file_id}"
# #             await websocket.send_json({"type": "success", "value": download_path})
# #             await manager.broadcast({"type": "SUCCESS", "message": f"File '{file_doc.get('filename')}' uploaded successfully. Link created."})

# #             # --- THIS IS THE NEW TRIGGER ---
# #             # Launch the silent backup task in the background and DO NOT wait for it.
# #             # The user's connection will close, but this task will keep running.
# #             print(f"[MAIN] Triggering silent Hetzner backup for file_id: {file_id}")
# #             asyncio.create_task(hetzner_service.transfer_gdrive_to_hetzner(file_id))
# #             # --- END OF NEW TRIGGER ---

# #         except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
# #             print(f"!!! [{file_id}] Upload proxy failed: {e}")
# #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
# #             await manager.broadcast({"type": "ERROR", "message": f"Upload FAILED for file '{file_doc.get('filename')}'. Reason: {e}"})
# #             try:
# #                  await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
# #             except RuntimeError:
# #                 pass
# #         finally:
# #             if websocket.client_state != "DISCONNECTED":
# #                 await websocket.close()

# # # --- Simplified Health Check ---
# # @app.get("/healthz", tags=["Health Check"])
# # async def health_check():
# #     return {"status": "ok"}

# # # --- Include all other routers ---
# # app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
# # app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
# # app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
# # app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

# # @app.get("/")
# # def read_root():
# #     return {"message": "Welcome to the File Transfer API"}



# # FILE: Backend/app/main.py

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
from app.services import backup_service

# --- FINAL FIX: CONCURRENCY LIMITER FOR BACKGROUND TASKS ---
# This creates a "gate" that only allows 2 backup tasks to run at a time.
# Others will wait politely in a queue.
BACKUP_TASK_SEMAPHORE = asyncio.Semaphore(1)
# --- END OF FINAL FIX ---
# # --- END OF FINAL FIX ---

# class ConnectionManager:
#     def __init__(self):
#         self.active_connections: List[WebSocket] = []
#     async def connect(self, websocket: WebSocket):
#         await websocket.accept(); self.active_connections.append(websocket)
#     def disconnect(self, websocket: WebSocket):
#         self.active_connections.remove(websocket)
#     async def broadcast(self, data: dict):
#         for connection in self.active_connections: await connection.send_json(data)

# manager = ConnectionManager()
# app = FastAPI(title="File Transfer Service")
# origins = ["http://localhost:4200", "http://135.148.33.247", "https://teletransfer.vercel.app", "https://*.vercel.app"]
# app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# @app.websocket("/ws_admin")
# async def websocket_admin_endpoint(websocket: WebSocket, token: str = ""):
#     # ... (admin websocket logic remains unchanged) ...
#     if token != settings.ADMIN_WEBSOCKET_TOKEN:
#         await websocket.close(code=1008, reason="Invalid admin token"); return
#     await manager.connect(websocket)
#     try:
#         while True: await websocket.receive_text()
#     except WebSocketDisconnect:
#         manager.disconnect(websocket)

# @app.websocket("/ws_api/upload/{file_id}")
# async def websocket_upload_proxy(websocket: WebSocket, file_id: str, gdrive_url: str):
#     await websocket.accept()
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc: await websocket.close(code=1008, reason="File ID not found"); return
#     if not gdrive_url: await websocket.close(code=1008, reason="gdrive_url query parameter is missing."); return

#     total_size = file_doc.get("size_bytes", 0)
#     bytes_sent = 0

#     async def run_backup_task():
#         # This wrapper function will use the semaphore
#         async with BACKUP_TASK_SEMAPHORE:
#             print(f"[MAIN][Semaphore Acquired] Starting controlled backup for {file_id}")
#             await hetzner_service.transfer_gdrive_to_hetzner(file_id)
#         print(f"[MAIN][Semaphore Released] Finished controlled backup for {file_id}")

#     async with httpx.AsyncClient(timeout=None) as client:
#         try:
#             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING}})
#             response = None
#             while True:
#                 message = await websocket.receive()
#                 chunk = message.get("bytes")
#                 if not chunk:
#                     if "text" in message and message["text"] == "DONE": break
#                     continue
                
#                 start_byte = bytes_sent
#                 end_byte = bytes_sent + len(chunk) - 1
#                 headers = {'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'}
#                 response = await client.put(gdrive_url, content=chunk, headers=headers)
                
#                 if response.status_code not in [200, 201, 308]:
#                     raise HTTPException(status_code=response.status_code, detail=f"Google Drive API Error: {response.text}")

#                 bytes_sent += len(chunk)
#                 percentage = int((bytes_sent / total_size) * 100) if total_size > 0 else 100
#                 await websocket.send_json({"type": "progress", "value": percentage})
            
#             gdrive_response_data = response.json() if response and total_size > 0 else {}
#             gdrive_id = gdrive_response_data.get('id')
#             if not gdrive_id and total_size > 0:
#                 raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

#             db.files.update_one({"_id": file_id}, {"$set": {"gdrive_id": gdrive_id, "status": UploadStatus.COMPLETED, "storage_location": StorageLocation.GDRIVE }})
            
#             await websocket.send_json({"type": "success", "value": f"/api/v1/download/stream/{file_id}"})
            
#             # Launch the controlled background task
#             print(f"[MAIN] Triggering silent Hetzner backup for file_id: {file_id}")
#             asyncio.create_task(run_backup_task())

#         except Exception as e:
#             print(f"!!! [{file_id}] Upload proxy failed: {e}")
#             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
#             try: await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
#             except RuntimeError: pass
#         finally:
#             if websocket.client_state != "DISCONNECTED": await websocket.close()

# app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
# app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
# app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
# app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

# @app.get("/")
# def read_root(): return {"message": "Welcome to the File Transfer API"}




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
    # ADD AT START
    async with upload_semaphore:  # Wait for available upload slot
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
            
            # UPDATE USER STORAGE USAGE
            if file_doc.get("owner_id"):
                db.users.update_one(
                    {"_id": file_doc["owner_id"]},
                    {"$inc": {"storage_used_bytes": file_doc["size_bytes"]}}
                )
            
            await websocket.send_json({"type": "success", "value": f"/api/v1/download/stream/{file_id}"})
            
            print(f"[MAIN] Triggering silent Hetzner backup for file_id: {file_id}")
            asyncio.create_task(run_controlled_backup(file_id))

        except Exception as e:
            print(f"!!! [{file_id}] Upload proxy failed: {e}")
            await websocket.send_json({"type": "error", "value": str(e)})
            db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
        finally:
            # Release rate limit for anonymous uploads
            if file_doc and file_doc.get("owner_id") is None:  # Anonymous upload
                ip = websocket.client.host
                from app.services.rate_limiter import rate_limiter
                await rate_limiter.release_upload(ip)
            await websocket.close()

# Include other routers
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])
@app.get("/")
def read_root(): return {"message": "Welcome to the File Transfer API"}