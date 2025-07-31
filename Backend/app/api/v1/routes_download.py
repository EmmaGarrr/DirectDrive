# In file: Backend/app/api/v1/routes_download.py

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from urllib.parse import quote
import httpx

from app.db.mongodb import db
from app.core.config import settings
from app.services.google_drive_service import gdrive_pool_manager, async_stream_gdrive_file
from app.models.file import FileMetadataInDB, PreviewMetadataResponse

router = APIRouter()

@router.get(
    "/files/{file_id}/meta",
    response_model=FileMetadataInDB,
    summary="Get File Metadata"
)
def get_file_metadata(file_id: str):
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    return file_doc

@router.get(
    "/download/stream/{file_id}",
    summary="Stream File for Download"
)
async def stream_download(file_id: str, request: Request):
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")

    filename = file_doc.get("filename", "download")
    filesize = file_doc.get("size_bytes", 0)

    # This async generator now contains the smart fallback logic
    async def content_streamer():
        # --- PRIMARY ATTEMPT: GOOGLE DRIVE ---
        try:
            print(f"[STREAMER] Attempting primary download from Google Drive for '{filename}'...")
            gdrive_id = file_doc.get("gdrive_id")
            account_id = file_doc.get("gdrive_account_id")

            if not gdrive_id or not account_id:
                raise ValueError("Primary storage info (GDrive) is missing from metadata.")
            
            storage_account = gdrive_pool_manager.get_account_by_id(account_id)
            if not storage_account:
                raise ValueError(f"Configuration for GDrive account '{account_id}' not found.")

            # If successful, this loop will run and stream the file
            async for chunk in async_stream_gdrive_file(gdrive_id, account=storage_account):
                yield chunk
            
            print(f"[STREAMER] Successfully streamed '{filename}' from Google Drive.")
            return # IMPORTANT: Exit the generator after a successful primary download

        except Exception as e:
            print(f"!!! [STREAMER] Primary download from Google Drive failed: {e}. Attempting backup from Hetzner...")

        # --- FALLBACK ATTEMPT: HETZNER ---
        try:
            print(f"[STREAMER] Attempting fallback download from Hetzner for '{filename}'...")
            hetzner_path = file_doc.get("hetzner_remote_path")
            if not hetzner_path:
                raise ValueError("Backup storage info (Hetzner) is missing from metadata.")
            
            hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{hetzner_path}"
            auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            timeout = httpx.Timeout(10.0, read=3600.0)

            async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
                async with client.stream("GET", hetzner_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
            
            print(f"[STREAMER] Successfully streamed '{filename}' from Hetzner backup.")

        except Exception as e:
            print(f"!!! [STREAMER] Fallback download from Hetzner also failed for '{filename}': {e}")
            # If both attempts fail, the generator will simply stop, and the user
            # will receive an empty/failed download, which is the correct behavior.
    
    headers = {
        "Content-Length": str(filesize),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }

    return StreamingResponse(
        content=content_streamer(),
        media_type="application/octet-stream",
        headers=headers
    )

# --- NEW: Preview metadata endpoint ---
@router.get(
    "/preview/meta/{file_id}",
    response_model=PreviewMetadataResponse,
    summary="Get Preview Metadata",
    tags=["Preview"]
)
def get_preview_metadata(file_id: str):
    """
    Retrieves preview metadata for a specific file, including media information
    and streaming URLs for preview functionality.
    """
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Check if preview is available for this file type
    content_type = file_doc.get("content_type", "")
    preview_available = is_previewable_content_type(content_type)
    
    # Build streaming URLs
    base_url = getattr(settings, 'API_BASE_URL', 'http://localhost:8000')
    streaming_urls = {
        "full": f"{base_url}/api/v1/download/stream/{file_id}",
        "preview": f"{base_url}/api/v1/preview/stream/{file_id}"
    }
    
    # Get media info if available
    media_info = file_doc.get("media_info")
    
    return PreviewMetadataResponse(
        file_id=file_id,
        filename=file_doc.get("filename", ""),
        content_type=content_type,
        size_bytes=file_doc.get("size_bytes", 0),
        preview_available=preview_available,
        media_info=media_info,
        streaming_urls=streaming_urls
    )

# --- NEW: Preview stream endpoint ---
@router.get(
    "/preview/stream/{file_id}",
    summary="Stream File for Preview",
    tags=["Preview"]
)
async def stream_preview(file_id: str, request: Request, format: str = Query(None, description="Preview format: 'preview' or 'thumbnail'")):
    """
    Streams a file for preview with HTTP Range Request support.
    This endpoint is optimized for media streaming with partial content support.
    """
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")

    filename = file_doc.get("filename", "preview")
    filesize = file_doc.get("size_bytes", 0)
    content_type = file_doc.get("content_type", "application/octet-stream")

    # Check if preview is available for this content type
    if not is_previewable_content_type(content_type):
        raise HTTPException(status_code=400, detail="File type not supported for preview")

    # Handle HTTP Range Request for partial content
    range_header = request.headers.get("range")
    start_byte = 0
    end_byte = filesize - 1
    
    if range_header and range_header.startswith("bytes="):
        try:
            range_str = range_header[6:]  # Remove "bytes="
            if "-" in range_str:
                start_str, end_str = range_str.split("-", 1)
                start_byte = int(start_str) if start_str else 0
                end_byte = int(end_str) if end_str else filesize - 1
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid range header")

    # This async generator contains the preview streaming logic
    async def preview_streamer():
        # --- PRIMARY ATTEMPT: GOOGLE DRIVE ---
        try:
            print(f"[PREVIEW] Streaming preview from Google Drive for '{filename}'...")
            gdrive_id = file_doc.get("gdrive_id")
            account_id = file_doc.get("gdrive_account_id")

            if not gdrive_id or not account_id:
                raise ValueError("Primary storage info (GDrive) is missing from metadata.")
            
            storage_account = gdrive_pool_manager.get_account_by_id(account_id)
            if not storage_account:
                raise ValueError(f"Configuration for GDrive account '{account_id}' not found.")

            # Stream with range support (if the service supports it)
            async for chunk in async_stream_gdrive_file(gdrive_id, account=storage_account):
                yield chunk
            
            print(f"[PREVIEW] Successfully streamed preview for '{filename}' from Google Drive.")
            return

        except Exception as e:
            print(f"!!! [PREVIEW] Primary preview from Google Drive failed: {e}. Attempting backup from Hetzner...")

        # --- FALLBACK ATTEMPT: HETZNER ---
        try:
            print(f"[PREVIEW] Streaming preview from Hetzner for '{filename}'...")
            hetzner_path = file_doc.get("hetzner_remote_path")
            if not hetzner_path:
                raise ValueError("Backup storage info (Hetzner) is missing from metadata.")
            
            hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{hetzner_path}"
            auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            timeout = httpx.Timeout(10.0, read=3600.0)
            
            # Add range header for partial content
            headers = {}
            if range_header:
                headers["Range"] = range_header

            async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
                async with client.stream("GET", hetzner_url, headers=headers) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
            
            print(f"[PREVIEW] Successfully streamed preview for '{filename}' from Hetzner backup.")

        except Exception as e:
            print(f"!!! [PREVIEW] Fallback preview from Hetzner also failed for '{filename}': {e}")
            raise HTTPException(status_code=500, detail="Preview streaming failed")
    
    # Set appropriate headers for preview streaming
    content_length = end_byte - start_byte + 1
    headers = {
        "Content-Length": str(content_length),
        "Accept-Ranges": "bytes",
        "Content-Type": content_type
    }
    
    # Add Content-Range header for partial content responses
    if range_header:
        headers["Content-Range"] = f"bytes {start_byte}-{end_byte}/{filesize}"
        status_code = 206
    else:
        status_code = 200

    return StreamingResponse(
        content=preview_streamer(),
        media_type=content_type,
        headers=headers,
        status_code=status_code
    )

# --- NEW: Helper function to determine if content type is previewable ---
def is_previewable_content_type(content_type: str) -> bool:
    """
    Determines if a content type supports preview functionality.
    """
    previewable_types = [
        # Video formats
        "video/mp4", "video/webm", "video/avi", "video/mov", "video/quicktime",
        # Audio formats  
        "audio/mp3", "audio/wav", "audio/ogg", "audio/m4a", "audio/aac",
        # Image formats
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
        # Document formats
        "application/pdf",
        # Text formats
        "text/plain", "application/json", "text/xml", "text/css", 
        "text/javascript", "text/python", "text/html"
    ]
    
    return content_type.lower() in previewable_types