# In file: Backend/app/models/file.py

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
import datetime

# --- MODIFIED: Simplified for the new flow ---
class StorageLocation(str, Enum):
    GDRIVE = "gdrive"
    TELEGRAM = "telegram"

# --- MODIFIED: Simplified to reflect the direct-to-cloud flow ---
class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING_TO_DRIVE = "uploading_to_drive"
    TRANSFERRING_TO_TELEGRAM = "transferring_to_telegram" # Kept for UI feedback if needed later
    COMPLETED = "completed"
    FAILED = "failed"


class FileMetadataBase(BaseModel):
    filename: str
    size_bytes: int
    content_type: str

class FileMetadataCreate(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    # The initial storage location is now GDrive, as we go there directly.
    storage_location: StorageLocation = StorageLocation.GDRIVE
    status: UploadStatus = UploadStatus.PENDING
    gdrive_id: Optional[str] = None
    telegram_file_ids: Optional[List[str]] = None
    owner_id: Optional[str] = None

class FileMetadataInDB(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime
    storage_location: StorageLocation
    status: UploadStatus
    gdrive_id: Optional[str] = None
    telegram_file_ids: Optional[List[str]] = None
    owner_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

class InitiateUploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str