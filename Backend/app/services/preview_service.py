# In file: Backend/app/services/preview_service.py

import asyncio
import subprocess
import tempfile
import os
from typing import Optional, Dict, Any
from fastapi import HTTPException
import json

from app.db.mongodb import db
from app.models.file import MediaInfo, PreviewStatus
from app.services.google_drive_service import gdrive_pool_manager, async_stream_gdrive_file


class PreviewService:
    """
    Service for handling file preview functionality including media metadata extraction
    and preview generation for supported file types.
    """
    
    def __init__(self):
        self.supported_video_formats = [
            "video/mp4", "video/webm", "video/avi", "video/mov", "video/quicktime"
        ]
        self.supported_audio_formats = [
            "audio/mp3", "audio/wav", "audio/ogg", "audio/m4a", "audio/aac"
        ]
        self.supported_image_formats = [
            "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"
        ]
        self.supported_document_formats = [
            "application/pdf"
        ]
        self.supported_text_formats = [
            "text/plain", "application/json", "text/xml", "text/css", 
            "text/javascript", "text/python", "text/html"
        ]

    def is_previewable_content_type(self, content_type: str) -> bool:
        """
        Determines if a content type supports preview functionality.
        """
        all_supported = (
            self.supported_video_formats + 
            self.supported_audio_formats + 
            self.supported_image_formats + 
            self.supported_document_formats + 
            self.supported_text_formats
        )
        return content_type.lower() in all_supported

    def get_preview_type(self, content_type: str) -> str:
        """
        Returns the preview type for a given content type.
        """
        content_type_lower = content_type.lower()
        
        if content_type_lower in self.supported_video_formats:
            return "video"
        elif content_type_lower in self.supported_audio_formats:
            return "audio"
        elif content_type_lower in self.supported_image_formats:
            return "image"
        elif content_type_lower in self.supported_document_formats:
            return "document"
        elif content_type_lower in self.supported_text_formats:
            return "text"
        else:
            return "unknown"

    async def extract_media_info(self, file_id: str) -> Optional[MediaInfo]:
        """
        Extracts media information from a file using ffprobe (if available).
        Returns MediaInfo object with extracted metadata.
        """
        try:
            file_doc = db.files.find_one({"_id": file_id})
            if not file_doc:
                return None

            content_type = file_doc.get("content_type", "")
            if not self.is_previewable_content_type(content_type):
                return None

            # For now, return basic info without ffprobe
            # In production, you would use ffprobe to extract detailed metadata
            media_info = MediaInfo(
                format=self._get_format_from_content_type(content_type),
                duration=None,  # Would be extracted with ffprobe
                width=None,     # Would be extracted with ffprobe
                height=None,    # Would be extracted with ffprobe
                has_audio=None, # Would be extracted with ffprobe
                bitrate=None,   # Would be extracted with ffprobe
                fps=None,       # Would be extracted with ffprobe
                sample_rate=None, # Would be extracted with ffprobe
                channels=None   # Would be extracted with ffprobe
            )

            return media_info

        except Exception as e:
            print(f"Error extracting media info for file {file_id}: {e}")
            return None

    def _get_format_from_content_type(self, content_type: str) -> Optional[str]:
        """
        Extracts format from content type string.
        """
        if "/" in content_type:
            return content_type.split("/")[-1].upper()
        return None

    async def update_file_preview_status(self, file_id: str, status: PreviewStatus, media_info: Optional[MediaInfo] = None):
        """
        Updates the preview status and media info for a file in the database.
        """
        try:
            update_data = {
                "preview_status": status,
                "preview_available": status == PreviewStatus.AVAILABLE
            }
            
            if media_info:
                update_data["media_info"] = media_info.dict()

            db.files.update_one(
                {"_id": file_id},
                {"$set": update_data}
            )
            
            print(f"Updated preview status for file {file_id}: {status}")
            
        except Exception as e:
            print(f"Error updating preview status for file {file_id}: {e}")

    async def process_file_for_preview(self, file_id: str) -> bool:
        """
        Processes a file to make it available for preview.
        This includes extracting media info and updating the database.
        """
        try:
            # Update status to processing
            await self.update_file_preview_status(file_id, PreviewStatus.PROCESSING)
            
            # Extract media info
            media_info = await self.extract_media_info(file_id)
            
            # Update status based on success
            if media_info:
                await self.update_file_preview_status(file_id, PreviewStatus.AVAILABLE, media_info)
                return True
            else:
                await self.update_file_preview_status(file_id, PreviewStatus.FAILED)
                return False
                
        except Exception as e:
            print(f"Error processing file {file_id} for preview: {e}")
            await self.update_file_preview_status(file_id, PreviewStatus.FAILED)
            return False

    def get_preview_stream_url(self, file_id: str, base_url: str = "http://localhost:8000") -> str:
        """
        Generates the preview streaming URL for a file.
        """
        return f"{base_url}/api/v1/preview/stream/{file_id}"

    def get_full_stream_url(self, file_id: str, base_url: str = "http://localhost:8000") -> str:
        """
        Generates the full file streaming URL for a file.
        """
        return f"{base_url}/api/v1/download/stream/{file_id}"

    async def get_preview_metadata(self, file_id: str, base_url: str = "http://localhost:8000") -> Dict[str, Any]:
        """
        Gets complete preview metadata for a file.
        """
        try:
            file_doc = db.files.find_one({"_id": file_id})
            if not file_doc:
                raise HTTPException(status_code=404, detail="File not found")

            content_type = file_doc.get("content_type", "")
            preview_available = self.is_previewable_content_type(content_type)
            
            streaming_urls = {
                "full": self.get_full_stream_url(file_id, base_url),
                "preview": self.get_preview_stream_url(file_id, base_url)
            }

            return {
                "file_id": file_id,
                "filename": file_doc.get("filename", ""),
                "content_type": content_type,
                "size_bytes": file_doc.get("size_bytes", 0),
                "preview_available": preview_available,
                "preview_type": self.get_preview_type(content_type),
                "media_info": file_doc.get("media_info"),
                "streaming_urls": streaming_urls,
                "preview_status": file_doc.get("preview_status", PreviewStatus.NOT_AVAILABLE)
            }

        except Exception as e:
            print(f"Error getting preview metadata for file {file_id}: {e}")
            raise HTTPException(status_code=500, detail="Error retrieving preview metadata")

    async def batch_process_previews(self, file_ids: list) -> Dict[str, bool]:
        """
        Processes multiple files for preview in parallel.
        Returns a dictionary mapping file_id to success status.
        """
        tasks = [self.process_file_for_preview(file_id) for file_id in file_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            file_id: result if isinstance(result, bool) else False
            for file_id, result in zip(file_ids, results)
        }


# Global instance for use throughout the application
preview_service = PreviewService() 