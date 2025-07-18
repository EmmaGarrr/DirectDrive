# File: Backend/app/models/batch.py

from pydantic import BaseModel, Field
from typing import List, Optional
import datetime

class BatchMetadata(BaseModel):
    """
    Represents a batch of files. The _id will be our unique batch_id.
    """
    id: str = Field(..., alias="_id")
    file_ids: List[str] = Field(default_factory=list)
    creation_date: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    owner_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

class InitiateBatchRequest(BaseModel):
    """
    Defines the structure for a request from the frontend to initiate a batch upload.
    It contains a list of all files to be uploaded.
    """
    class FileInfo(BaseModel):
        filename: str
        size: int
        content_type: str
    
    files: List[FileInfo]

class InitiateBatchResponse(BaseModel):
    """
    Defines the structure of the response the backend sends after initiating a batch.
    """
    class FileUploadInfo(BaseModel):
        file_id: str
        gdrive_upload_url: str
        # We also return the original filename to help the frontend match them up.
        original_filename: str

    batch_id: str
    files: List[FileUploadInfo]