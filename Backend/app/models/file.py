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
#     content_type: str


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