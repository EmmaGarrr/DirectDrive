# --- ADDED: Imports needed for the WebSocket logic ---
import httpx
from celery import chain
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# --- MODIFIED: Import only the http_upload_router ---
from app.api.v1.routes_upload import router as http_upload_router
from app.api.v1 import routes_auth, routes_download
from app.api.v1 import routes_batch_upload

# --- ADDED: Imports for models and services used by the WebSocket ---
from app.db.mongodb import db
from app.models.file import UploadStatus, StorageLocation
from app.tasks.telegram_uploader_task import transfer_to_telegram, finalize_and_delete

# --- Create a SINGLE FastAPI application instance ---
app = FastAPI(title="File Transfer Service")

origins = [
    "http://localhost:4200",
    "https://teletransfer.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- THIS IS THE DEFINITIVE FIX: WebSocket route defined directly on the app ---
@app.websocket("/ws_api/upload/{file_id}")
async def websocket_upload_proxy(
    websocket: WebSocket,
    file_id: str,
    gdrive_url: str  # FastAPI automatically treats this as a query parameter
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
            db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING_TO_DRIVE}})
            
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
                    error_detail = f"Google Drive API Error: {response.text}"
                    print(f"!!! [{file_id}] {error_detail}")
                    raise HTTPException(status_code=response.status_code, detail=error_detail)

                bytes_sent += len(chunk)
                percentage = int((bytes_sent / total_size) * 100)
                await websocket.send_json({"type": "progress", "value": percentage})

            if response.status_code not in [200, 201]:
                 raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
            gdrive_response_data = response.json()
            gdrive_id = gdrive_response_data.get('id')

            if not gdrive_id:
                raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

            print(f"[{file_id}] GDrive upload successful. GDrive ID: {gdrive_id}")

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
            
            print(f"[{file_id}] Dispatching silent Telegram archival task chain.")
            task_chain = chain(
                transfer_to_telegram.s(gdrive_id=gdrive_id, file_id=file_id),
                finalize_and_delete.s(file_id=file_id, gdrive_id=gdrive_id)
            )
            task_chain.delay()

        except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
            print(f"!!! [{file_id}] Upload proxy failed: {e}")
            db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
            try:
                 await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
            except RuntimeError:
                pass
        finally:
            if websocket.client_state != "DISCONNECTED":
                await websocket.close()
            print(f"[{file_id}] WebSocket proxy connection closed for file_id.")


# --- Include the standard HTTP routers ---
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(http_upload_router, prefix="/api/v1", tags=["Upload"])
app.include_router(routes_download.router, prefix="/api/v1", tags=["Download"])
app.include_router(routes_batch_upload.router, prefix="/api/v1/batch", tags=["Batch Upload"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the File Transfer API"}