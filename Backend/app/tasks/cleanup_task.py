from datetime import datetime, timedelta
import os
import logging
from app.db.mongodb import db
from app.models.file import UploadStatus
from app.core.config import settings

# Configure logging
logger = logging.getLogger("cleanup_task")

# Constants for cleanup thresholds
ORPHANED_UPLOAD_HOURS = 24  # Consider uploads orphaned after 24 hours
FAILED_UPLOAD_HOURS = 48    # Keep failed uploads for 48 hours before cleanup
TEMP_FILE_HOURS = 6         # Keep temporary files for 6 hours


async def cleanup_orphaned_uploads():
    """
    Cleans up orphaned uploads that were initiated but never completed.
    This helps conserve disk space on the limited SSD.
    """
    logger.info("Starting orphaned uploads cleanup task")
    
    # Calculate cutoff times
    now = datetime.utcnow()
    orphaned_cutoff = now - timedelta(hours=ORPHANED_UPLOAD_HOURS)
    failed_cutoff = now - timedelta(hours=FAILED_UPLOAD_HOURS)
    
    try:
        # 1. Find and clean up uploads stuck in INITIATED state
        orphaned_uploads = db.uploads.find({
            "status": UploadStatus.INITIATED,
            "created_at": {"$lt": orphaned_cutoff}
        })
        
        orphaned_count = 0
        for upload in orphaned_uploads:
            upload_id = upload.get("_id")
            temp_path = upload.get("temp_path")
            
            # Delete the temporary file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    logger.info(f"Deleted orphaned upload temp file: {temp_path}")
                except Exception as e:
                    logger.error(f"Failed to delete orphaned temp file {temp_path}: {e}")
            
            # Update the upload status to FAILED
            db.uploads.update_one(
                {"_id": upload_id},
                {"$set": {"status": UploadStatus.FAILED, "error": "Upload orphaned and cleaned up"}}
            )
            orphaned_count += 1
        
        logger.info(f"Cleaned up {orphaned_count} orphaned uploads")
        
        # 2. Clean up old failed uploads
        failed_result = db.uploads.delete_many({
            "status": UploadStatus.FAILED,
            "updated_at": {"$lt": failed_cutoff}
        })
        
        logger.info(f"Deleted {failed_result.deleted_count} old failed uploads")
        
        # 3. Clean up temporary files in the upload directory
        temp_dir = settings.UPLOAD_DIR
        if os.path.exists(temp_dir) and os.path.isdir(temp_dir):
            temp_cutoff = now - timedelta(hours=TEMP_FILE_HOURS)
            temp_count = 0
            
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                if os.path.isfile(file_path):
                    file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_modified < temp_cutoff:
                        try:
                            os.remove(file_path)
                            temp_count += 1
                        except Exception as e:
                            logger.error(f"Failed to delete temp file {file_path}: {e}")
            
            logger.info(f"Cleaned up {temp_count} old temporary files")
        
        return {
            "orphaned_uploads_cleaned": orphaned_count,
            "failed_uploads_deleted": failed_result.deleted_count if hasattr(failed_result, 'deleted_count') else 0,
            "temp_files_deleted": temp_count
        }
    
    except Exception as e:
        logger.error(f"Error during cleanup task: {e}")
        raise
