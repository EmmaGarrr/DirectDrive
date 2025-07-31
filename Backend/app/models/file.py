# In file: Backend/app/models/file.py

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
import datetime

# --- MODIFIED: Added Hetzner as a possible storage location ---
class StorageLocation(str, Enum):
    GDRIVE = "gdrive"
    HETZNER = "hetzner"

class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"

# --- NEW: A status to track the background backup process ---
class BackupStatus(str, Enum):
    NONE = "none"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

# --- NEW: Preview status for media files ---
class PreviewStatus(str, Enum):
    NOT_AVAILABLE = "not_available"
    PROCESSING = "processing"
    AVAILABLE = "available"
    FAILED = "failed"

# --- NEW: Media info model for preview metadata ---
class MediaInfo(BaseModel):
    duration: Optional[float] = None  # Duration in seconds
    width: Optional[int] = None       # Video/image width
    height: Optional[int] = None      # Video/image height
    has_audio: Optional[bool] = None  # Whether video has audio track
    format: Optional[str] = None      # Media format (mp4, webm, etc.)
    bitrate: Optional[int] = None     # Bitrate in kbps
    fps: Optional[float] = None       # Frames per second for video
    sample_rate: Optional[int] = None # Sample rate for audio (Hz)
    channels: Optional[int] = None    # Number of audio channels

# --- NEW: Streaming URLs model ---
class StreamingUrls(BaseModel):
    full: str = Field(..., description="Full file download URL")
    preview: str = Field(..., description="Preview streaming URL")

class FileMetadataBase(BaseModel):
    filename: str
    size_bytes: int
    content_type: str

class FileMetadataCreate(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    
    # Primary storage info
    storage_location: Optional[StorageLocation] = None
    status: UploadStatus = UploadStatus.PENDING
    gdrive_id: Optional[str] = None
    gdrive_account_id: Optional[str] = None
    
    # --- NEW: Fields for backup storage ---
    backup_status: BackupStatus = BackupStatus.NONE
    backup_location: Optional[StorageLocation] = None
    hetzner_remote_path: Optional[str] = None
    
    # --- NEW: Preview metadata fields ---
    preview_status: PreviewStatus = PreviewStatus.NOT_AVAILABLE
    preview_available: bool = False
    media_info: Optional[MediaInfo] = None
    streaming_urls: Optional[StreamingUrls] = None
    
    owner_id: Optional[str] = None
    batch_id: Optional[str] = None

class FileMetadataInDB(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime

    # Primary storage info
    storage_location: Optional[StorageLocation] = None
    status: UploadStatus
    gdrive_id: Optional[str] = None
    gdrive_account_id: Optional[str] = None

    # --- NEW: Fields for backup storage ---
    backup_status: BackupStatus
    backup_location: Optional[StorageLocation] = None
    hetzner_remote_path: Optional[str] = None

    # --- NEW: Preview metadata fields ---
    preview_status: PreviewStatus = PreviewStatus.NOT_AVAILABLE
    preview_available: bool = False
    media_info: Optional[MediaInfo] = None
    streaming_urls: Optional[StreamingUrls] = None

    owner_id: Optional[str] = None
    batch_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

class InitiateUploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str

# --- NEW: Preview metadata response model ---
class PreviewMetadataResponse(BaseModel):
    file_id: str
    filename: str
    content_type: str
    size_bytes: int
    preview_available: bool
    media_info: Optional[MediaInfo] = None
    streaming_urls: StreamingUrls

# --- NEW: Preview stream request model ---
class PreviewStreamRequest(BaseModel):
    format: Optional[str] = Field(None, description="Preview format: 'preview' or 'thumbnail'")