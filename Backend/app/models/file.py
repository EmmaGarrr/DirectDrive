# In file: Backend/app/models/file.py

from pydantic import BaseModel, Field
from typing import List, Optional
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

    owner_id: Optional[str] = None
    batch_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

class InitiateUploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str