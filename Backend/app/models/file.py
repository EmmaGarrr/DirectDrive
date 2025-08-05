# # # # In file: Backend/app/models/file.py

# # # from pydantic import BaseModel, Field
# # # from typing import List, Optional
# # # from enum import Enum
# # # import datetime

# # # # --- MODIFIED: Simplified for the new flow ---
# # # class StorageLocation(str, Enum):
# # #     GDRIVE = "gdrive"
# # #     TELEGRAM = "telegram"

# # # # --- MODIFIED: Simplified to reflect the direct-to-cloud flow ---
# # # class UploadStatus(str, Enum):
# # #     PENDING = "pending"
# # #     UPLOADING_TO_DRIVE = "uploading_to_drive"
# # #     TRANSFERRING_TO_TELEGRAM = "transferring_to_telegram" # Kept for UI feedback if needed later
# # #     COMPLETED = "completed"
# # #     FAILED = "failed"


# # # class FileMetadataBase(BaseModel):
# # #     filename: str
# # #     size_bytes: int
# # #     content_type: str

# # # class FileMetadataCreate(FileMetadataBase):
# # #     id: str = Field(..., alias="_id")
# # #     upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
# # #     # The initial storage location is now GDrive, as we go there directly.
# # #     storage_location: StorageLocation = StorageLocation.GDRIVE
# # #     status: UploadStatus = UploadStatus.PENDING
# # #     gdrive_id: Optional[str] = None
# # #     telegram_file_ids: Optional[List[str]] = None
# # #     owner_id: Optional[str] = None

# # # class FileMetadataInDB(FileMetadataBase):
# # #     id: str = Field(..., alias="_id")
# # #     upload_date: datetime.datetime
# # #     storage_location: StorageLocation
# # #     status: UploadStatus
# # #     gdrive_id: Optional[str] = None
# # #     telegram_file_ids: Optional[List[str]] = None
# # #     owner_id: Optional[str] = None

# # #     class Config:
# # #         populate_by_name = True
# # #         from_attributes = True

# # # class InitiateUploadRequest(BaseModel):
# # #     filename: str
# # #     size: int
# # #     content_type: str





# # # # In file: Backend/app/models/file.py

# # # from pydantic import BaseModel, Field
# # # from typing import List, Optional
# # # from enum import Enum
# # # import datetime

# # # # --- StorageLocation and UploadStatus enums remain unchanged ---
# # # class StorageLocation(str, Enum):
# # #     GDRIVE = "gdrive"
# # #     TELEGRAM = "telegram"

# # # class UploadStatus(str, Enum):
# # #     PENDING = "pending"
# # #     UPLOADING_TO_DRIVE = "uploading_to_drive"
# # #     TRANSFERRING_TO_TELEGRAM = "transferring_to_telegram"
# # #     COMPLETED = "completed"
# # #     FAILED = "failed"


# # # class FileMetadataBase(BaseModel):
# # #     filename: str
# # #     size_bytes: int
# # #     content_type: str

# # # class FileMetadataCreate(FileMetadataBase):
# # #     id: str = Field(..., alias="_id")
# # #     upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
# # #     storage_location: StorageLocation = StorageLocation.GDRIVE
# # #     status: UploadStatus = UploadStatus.PENDING
# # #     gdrive_id: Optional[str] = None
# # #     telegram_file_ids: Optional[List[str]] = None
# # #     owner_id: Optional[str] = None
# # #     batch_id: Optional[str] = None # <--- ADD THIS LINE

# # # class FileMetadataInDB(FileMetadataBase):
# # #     id: str = Field(..., alias="_id")
# # #     upload_date: datetime.datetime
# # #     storage_location: StorageLocation
# # #     status: UploadStatus
# # #     gdrive_id: Optional[str] = None
# # #     telegram_file_ids: Optional[List[str]] = None
# # #     owner_id: Optional[str] = None
# # #     batch_id: Optional[str] = None # <--- ADD THIS LINE

# # #     class Config:
# # #         populate_by_name = True
# # #         from_attributes = True

# # # class InitiateUploadRequest(BaseModel):
# # #     filename: str
# # #     size: int
# # #     content_type: str



# # #########################################################################################################
# # #########################################################################################################
# # #########################################################################################################



# # # In file: Backend/app/models/file.py

# # from pydantic import BaseModel, Field
# # from typing import List, Optional
# # from enum import Enum
# # import datetime

# # # --- MODIFIED: Simplified StorageLocation ---
# # class StorageLocation(str, Enum):
# #     GDRIVE = "gdrive"

# # # --- MODIFIED: Simplified UploadStatus ---
# # class UploadStatus(str, Enum):
# #     PENDING = "pending"
# #     UPLOADING = "uploading"
# #     COMPLETED = "completed"
# #     FAILED = "failed"

# # class FileMetadataBase(BaseModel):
# #     filename: str
# #     size_bytes: int
# #     content_type: str

# # class FileMetadataCreate(FileMetadataBase):
# #     id: str = Field(..., alias="_id")
# #     upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
# #     storage_location: Optional[StorageLocation] = None # Location is set upon completion
# #     status: UploadStatus = UploadStatus.PENDING
# #     gdrive_id: Optional[str] = None
# #     # --- REMOVED: telegram_file_ids field ---
# #     owner_id: Optional[str] = None
# #     batch_id: Optional[str] = None

# # class FileMetadataInDB(FileMetadataBase):
# #     id: str = Field(..., alias="_id")
# #     upload_date: datetime.datetime
# #     storage_location: Optional[StorageLocation] = None
# #     status: UploadStatus
# #     gdrive_id: Optional[str] = None
# #     # --- REMOVED: telegram_file_ids field ---
# #     owner_id: Optional[str] = None
# #     batch_id: Optional[str] = None

# #     class Config:
# #         populate_by_name = True
# #         from_attributes = True

# # class InitiateUploadRequest(BaseModel):
# #     filename: str
# #     size: int
# #     content_type: str




# # In file: Backend/app/models/file.py

# from pydantic import BaseModel, Field
# from typing import List, Optional
# from enum import Enum
# import datetime

# class StorageLocation(str, Enum):
#     GDRIVE = "gdrive"

# class UploadStatus(str, Enum):
#     PENDING = "pending"
#     UPLOADING = "uploading"
#     COMPLETED = "completed"
#     FAILED = "failed"

# class FileMetadataBase(BaseModel):
#     filename: str
#     size_bytes: int
#     content_type: str

# class FileMetadataCreate(FileMetadataBase):
#     id: str = Field(..., alias="_id")
#     upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
#     storage_location: Optional[StorageLocation] = None
#     status: UploadStatus = UploadStatus.PENDING
#     gdrive_id: Optional[str] = None
    
#     # --- ADDED: This field will store which account was used for the upload ---
#     gdrive_account_id: Optional[str] = None
    
#     owner_id: Optional[str] = None
#     batch_id: Optional[str] = None

# class FileMetadataInDB(FileMetadataBase):
#     id: str = Field(..., alias="_id")
#     upload_date: datetime.datetime
#     storage_location: Optional[StorageLocation] = None
#     status: UploadStatus
#     gdrive_id: Optional[str] = None
    
#     # --- ADDED: This field is read from the database ---
#     gdrive_account_id: Optional[str] = None

#     owner_id: Optional[str] = None
#     batch_id: Optional[str] = None

#     class Config:
#         populate_by_name = True
#         from_attributes = True

# class InitiateUploadRequest(BaseModel):
#     filename: str
#     size: int
# In file: Backend/app/models/file.py

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from enum import Enum
import datetime

class StorageLocation(str, Enum):
    GDRIVE = "gdrive"
    HETZNER = "hetzner"

class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"

class BackupStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class FileStorageStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"

class FileMetadataBase(BaseModel):
    filename: str
    size_bytes: int
    content_type: str
    file_type: Optional[str] = None  # e.g., 'image', 'video', 'document'

class FileStorageInfo(BaseModel):
    """Tracks file information in a specific storage location"""
    file_id: Optional[str] = None  # ID in the storage system (e.g., Google Drive ID)
    path: Optional[str] = None  # Path in the storage system
    status: FileStorageStatus = FileStorageStatus.PENDING
    url: Optional[HttpUrl] = None  # Direct download URL if available
    error: Optional[str] = None  # Error message if status is FAILED
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    size_bytes: Optional[int] = None  # Actual size in storage (may differ from original)
    metadata: Dict[str, Any] = Field(default_factory=dict)  # Additional storage-specific metadata

class FileMetadataCreate(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    
    # Primary storage (Google Drive)
    gdrive_info: Optional[FileStorageInfo] = None
    
    # Backup storage (Hetzner)
    hetzner_info: Optional[FileStorageInfo] = None
    
    # Status tracking
    status: UploadStatus = UploadStatus.PENDING
    backup_status: BackupStatus = BackupStatus.NONE
    
    # Owner and relationships
    owner_id: Optional[str] = None
    owner_email: Optional[str] = None  # Denormalized for easier querying
    batch_id: Optional[str] = None
    
    # Derived properties for backward compatibility
    @property
    def gdrive_id(self) -> Optional[str]:
        return self.gdrive_info.file_id if self.gdrive_info else None
        
    @property
    def storage_location(self) -> Optional[StorageLocation]:
        if self.hetzner_info and self.hetzner_info.status == FileStorageStatus.AVAILABLE:
            return StorageLocation.HETZNER
        if self.gdrive_info and self.gdrive_info.status == FileStorageStatus.AVAILABLE:
            return StorageLocation.GDRIVE
        return None

class FileMetadataInDB(FileMetadataBase):
    id: str = Field(..., alias="_id")
    upload_date: datetime.datetime
    
    # Storage information
    gdrive_info: Optional[FileStorageInfo] = None
    hetzner_info: Optional[FileStorageInfo] = None
    
    # Status tracking
    status: UploadStatus = UploadStatus.PENDING
    backup_status: BackupStatus = BackupStatus.NONE
    
    # Owner and relationships
    owner_id: Optional[str] = None
    owner_email: Optional[str] = None
    batch_id: Optional[str] = None
    
    # Timestamps
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    
    # Derived properties for backward compatibility
    @property
    def gdrive_id(self) -> Optional[str]:
        return self.gdrive_info.file_id if self.gdrive_info else None
        
    @property
    def storage_location(self) -> Optional[StorageLocation]:
        if self.hetzner_info and self.hetzner_info.status == FileStorageStatus.AVAILABLE:
            return StorageLocation.HETZNER
        if self.gdrive_info and self.gdrive_info.status == FileStorageStatus.AVAILABLE:
            return StorageLocation.GDRIVE
        return None
    
    @property
    def gdrive_account_id(self) -> Optional[str]:
        return self.gdrive_info.metadata.get('account_id') if self.gdrive_info else None
    
    @property
    def hetzner_remote_path(self) -> Optional[str]:
        return self.hetzner_info.path if self.hetzner_info else None

    class Config:
        populate_by_name = True
        from_attributes = True
        json_encoders = {
            datetime.datetime: lambda v: v.isoformat() if v else None
        }

class InitiateUploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str