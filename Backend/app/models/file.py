# In file: Backend/app/models/file.py

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
import datetime

# --- MODIFIED: Added Hetzner as a possible storage location ---
class StorageLocation(str, Enum):
    GDRIVE = "gdrive"
    HETZNER = "hetzner"
    ARCHIVED = "archived"  # NEW: For archived files

class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"  # NEW: For quarantined files
    ARCHIVED = "archived"  # NEW: For archived files

# --- NEW: A status to track the background backup process ---
class BackupStatus(str, Enum):
    NONE = "none"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

# --- NEW: Action history tracking ---
class ActionHistory(BaseModel):
    action: str
    performed_by: str
    performed_at: datetime.datetime
    reason: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None

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
    gdrive_file_path: Optional[str] = None  # NEW: Google Drive file path
    
    # --- NEW: Fields for backup storage ---
    backup_status: BackupStatus = BackupStatus.NONE
    backup_location: Optional[StorageLocation] = None
    hetzner_remote_path: Optional[str] = None
    
    # --- NEW: Archive system fields ---
    archived: bool = False
    archived_at: Optional[datetime.datetime] = None
    archived_by: Optional[str] = None
    archive_reason: Optional[str] = None
    original_storage_location: Optional[StorageLocation] = None  # Where file was before archiving
    
    # --- NEW: Quarantine fields ---
    quarantined: bool = False
    quarantined_at: Optional[datetime.datetime] = None
    quarantined_by: Optional[str] = None
    quarantine_reason: Optional[str] = None
    
    # --- NEW: Action history ---
    action_history: List[ActionHistory] = []
    
    # --- NEW: Integrity checking fields ---
    integrity_checksum: Optional[str] = None
    last_integrity_check: Optional[datetime.datetime] = None
    integrity_status: Optional[str] = None  # 'verified', 'corrupted', 'unknown'
    
    # --- NEW: Error tracking fields ---
    upload_error: Optional[str] = None
    upload_error_details: Optional[str] = None
    backup_error: Optional[str] = None
    backup_error_details: Optional[str] = None
    
    # --- NEW: Deletion tracking fields ---
    deleted_at: Optional[datetime.datetime] = None
    deleted_by: Optional[str] = None
    deletion_reason: Optional[str] = None
    
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
    gdrive_file_path: Optional[str] = None  # NEW: Google Drive file path

    # --- NEW: Fields for backup storage ---
    backup_status: BackupStatus
    backup_location: Optional[StorageLocation] = None
    hetzner_remote_path: Optional[str] = None

    # --- NEW: Archive system fields ---
    archived: bool = False
    archived_at: Optional[datetime.datetime] = None
    archived_by: Optional[str] = None
    archive_reason: Optional[str] = None
    original_storage_location: Optional[StorageLocation] = None
    
    # --- NEW: Quarantine fields ---
    quarantined: bool = False
    quarantined_at: Optional[datetime.datetime] = None
    quarantined_by: Optional[str] = None
    quarantine_reason: Optional[str] = None
    
    # --- NEW: Action history ---
    action_history: List[ActionHistory] = []
    
    # --- NEW: Integrity checking fields ---
    integrity_checksum: Optional[str] = None
    last_integrity_check: Optional[datetime.datetime] = None
    integrity_status: Optional[str] = None

    # --- NEW: Error tracking fields ---
    upload_error: Optional[str] = None
    upload_error_details: Optional[str] = None
    backup_error: Optional[str] = None
    backup_error_details: Optional[str] = None
    
    # --- NEW: Deletion tracking fields ---
    deleted_at: Optional[datetime.datetime] = None
    deleted_by: Optional[str] = None
    deletion_reason: Optional[str] = None

    owner_id: Optional[str] = None
    batch_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

class InitiateUploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str

# --- NEW: Archive management models ---
class ArchiveFileRequest(BaseModel):
    reason: Optional[str] = None

class RestoreFileRequest(BaseModel):
    reason: Optional[str] = None

class IntegrityCheckResult(BaseModel):
    status: str  # 'verified', 'corrupted', 'unknown'
    checksum_match: bool
    corruption_detected: bool
    file_accessible: bool
    last_check: datetime.datetime
    check_performed_by: str
    details: Optional[str] = None