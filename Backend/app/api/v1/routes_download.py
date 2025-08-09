# In file: Backend/app/api/v1/routes_download.py

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from urllib.parse import quote
import httpx # --- NEW: Import httpx for Hetzner downloads ---

from app.db.mongodb import db
from app.core.config import settings # --- NEW: Import settings for credentials ---
from app.services.google_drive_service import gdrive_pool_manager, async_stream_gdrive_file
from app.models.file import FileMetadataInDB

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

def is_previewable(content_type: str) -> bool:
    """Check if file type supports preview"""
    previewable_types = [
        "image/", "video/", "audio/", "text/", "application/pdf"
    ]
    return any(content_type.startswith(ptype) for ptype in previewable_types)

@router.get(
    "/preview/meta/{file_id}",
    summary="Get File Preview Metadata"
)
def get_file_preview_metadata(file_id: str):
    """Get metadata for file preview - returns graceful response for non-previewable files"""
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    
    content_type = file_doc.get("content_type", "")
    filename = file_doc.get("filename", "")
    
    # Check if file is previewable
    preview_available = is_previewable(content_type)
    
    if not preview_available:
        # Graceful handling for non-previewable files (like ZIP)
        return {
            "file_id": file_id,
            "filename": filename,
            "content_type": content_type,
            "preview_available": False,
            "preview_type": "none",
            "message": f"Preview not available for {content_type} files",
            "can_stream": False,
            "suggested_action": "download"
        }
    
    # Return preview metadata for previewable files
    return {
        "file_id": file_id,
        "filename": filename,
        "content_type": content_type,
        "preview_available": True,
        "preview_type": "thumbnail" if content_type.startswith("image/") else "viewer",
        "preview_url": f"/api/v1/download/stream/{file_id}",
        "can_stream": content_type.startswith(("video/", "audio/")),
        "suggested_action": "preview"
    }

@router.get(
    "/preview/stream/{file_id}",
    summary="Stream File for Preview"
)
async def stream_preview(file_id: str, request: Request):
    """Stream file content for preview (same as download but with different headers)"""
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    
    content_type = file_doc.get("content_type", "")
    
    # Check if file is previewable
    if not is_previewable(content_type):
        raise HTTPException(
            status_code=400, 
            detail=f"Preview not supported for {content_type} files. Please download instead."
        )

    filename = file_doc.get("filename", "preview")
    filesize = file_doc.get("size_bytes", 0)

    # Reuse the same streaming logic as download
    async def content_streamer():
        try:
            print(f"[PREVIEW] Attempting to stream preview for '{filename}'...")
            gdrive_id = file_doc.get("gdrive_id")
            account_id = file_doc.get("gdrive_account_id")

            if not gdrive_id or not account_id:
                raise ValueError("Primary storage info (GDrive) is missing from metadata.")
            
            storage_account = gdrive_pool_manager.get_account_by_id(account_id)
            if not storage_account:
                raise ValueError(f"Configuration for GDrive account '{account_id}' not found.")

            async for chunk in async_stream_gdrive_file(gdrive_id, account=storage_account):
                yield chunk
            
            print(f"[PREVIEW] Successfully streamed preview for '{filename}' from Google Drive.")
            return

        except Exception as e:
            print(f"!!! [PREVIEW] Primary preview from Google Drive failed: {e}. Attempting backup from Hetzner...")

        try:
            print(f"[PREVIEW] Attempting fallback preview from Hetzner for '{filename}'...")
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
            
            print(f"[PREVIEW] Successfully streamed preview for '{filename}' from Hetzner backup.")

        except Exception as e:
            print(f"!!! [PREVIEW] Fallback preview from Hetzner also failed for '{filename}': {e}")
    
    # Set appropriate headers for preview (inline instead of attachment)
    headers = {
        "Content-Length": str(filesize),
        "Content-Type": content_type,
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"
    }

    return StreamingResponse(
        content=content_streamer(),
        media_type=content_type,
        headers=headers
    )