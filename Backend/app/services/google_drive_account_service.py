import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.db.mongodb import db
from app.models.google_drive_account import (
    GoogleDriveAccountDB, 
    GoogleDriveAccountCreate, 
    GoogleDriveAccountUpdate,
    GoogleDriveAccountResponse
)
from app.core.config import settings

SCOPES = ['https://www.googleapis.com/auth/drive']

class GoogleDriveAccountService:
    """Service for managing Google Drive accounts"""
    
    @staticmethod
    async def initialize_service():
        """Initialize the service on startup"""
        try:
            print("[GoogleDriveAccountService] Initializing service...")
            await GoogleDriveAccountService._ensure_collection_exists()
            await GoogleDriveAccountService.migrate_env_accounts_to_db()
            await GoogleDriveAccountService.sync_with_existing_pool()
            print("[GoogleDriveAccountService] Service initialized successfully")
        except Exception as e:
            print(f"[GoogleDriveAccountService] Error during initialization: {e}")
    
    @staticmethod
    async def _ensure_collection_exists():
        """Ensure the google_drive_accounts collection exists"""
        try:
            # This will create the collection if it doesn't exist
            db.google_drive_accounts.find_one()
        except Exception as e:
            print(f"Error ensuring collection exists: {e}")
    
    @staticmethod
    async def migrate_env_accounts_to_db(force: bool = False):
        """Migrate accounts from environment variables to database"""
        from app.core.config import settings
        
        # Check if we already have accounts in the database
        existing_count = db.google_drive_accounts.count_documents({})
        if existing_count > 0 and not force:
            print(f"Database already has {existing_count} accounts, skipping migration")
            return
        
        if force:
            print("Force migration requested, will re-migrate all accounts")
            # Clear existing accounts
            db.google_drive_accounts.delete_many({})
            print("Cleared existing accounts from database")
        
        # Migrate accounts from environment variables
        print(f"[MIGRATION] Found {len(settings.GDRIVE_ACCOUNTS)} accounts in environment")
        for i, account_config in enumerate(settings.GDRIVE_ACCOUNTS):
            print(f"[MIGRATION] Processing account {i+1}: {account_config.id} ({account_config.client_id[:10]}...)")
        
        migrated_count = 0
        for i, account_config in enumerate(settings.GDRIVE_ACCOUNTS, 1):
            try:
                # Check if account already exists
                existing = db.google_drive_accounts.find_one({"account_id": account_config.id})
                if existing:
                    print(f"Account {account_config.id} already exists in database")
                    continue
                
                # Try to get actual email from Google Drive API
                actual_email = f"account_{i}@directdrive.service.com"  # Default email
                try:
                    # Create temporary credentials to get account info
                    creds = Credentials.from_authorized_user_info(
                        info={
                            "client_id": account_config.client_id,
                            "client_secret": account_config.client_secret,
                            "refresh_token": account_config.refresh_token,
                        },
                        scopes=['https://www.googleapis.com/auth/drive']
                    )
                    service = build('drive', 'v3', credentials=creds, static_discovery=False)
                    about = service.about().get(fields="user").execute()
                    if 'user' in about and 'emailAddress' in about['user']:
                        actual_email = about['user']['emailAddress']
                except Exception as e:
                    print(f"Could not fetch email for account {account_config.id}: {e}")
                    # Continue with default email
                
                # Create account document
                account_doc = GoogleDriveAccountDB(
                    account_id=account_config.id,
                    email=actual_email,
                    alias=f"Account {i} (Migrated)",
                    client_id=account_config.client_id,
                    client_secret=account_config.client_secret,
                    refresh_token=account_config.refresh_token,
                    folder_id=account_config.folder_id,
                    is_active=True
                )
                
                # Insert into database (exclude _id field to let MongoDB auto-generate)
                insert_data = account_doc.dict(by_alias=True, exclude={"id"})
                print(f"[MIGRATION] Inserting account {account_config.id} with data: {list(insert_data.keys())}")
                result = db.google_drive_accounts.insert_one(insert_data)
                account_doc.id = result.inserted_id
                
                # Update storage quota and usage (don't fail migration if this fails)
                try:
                    await GoogleDriveAccountService._update_account_quota(account_doc)
                except Exception as e:
                    print(f"Could not update quota for account {account_config.id} during migration: {e}")
                    # Continue with migration
                
                migrated_count += 1
                print(f"Migrated account {account_config.id} to database")
                
            except Exception as e:
                print(f"Error migrating account {account_config.id}: {e}")
        
        if migrated_count > 0:
            print(f"Successfully migrated {migrated_count} accounts from environment to database")
        else:
            print("No accounts migrated (none found in environment or all already exist)")
    
    @staticmethod
    async def sync_with_existing_pool():
        """Sync database accounts with the existing Google Drive pool manager"""
        try:
            from app.services.google_drive_service import gdrive_pool_manager
            
            # Get accounts from database
            db_accounts = await GoogleDriveAccountService.get_all_accounts()
            
            # Update pool manager if needed
            if db_accounts and hasattr(gdrive_pool_manager, 'accounts'):
                # Check if pool manager needs updating
                pool_account_ids = {acc.id for acc in gdrive_pool_manager.accounts}
                db_account_ids = {acc.account_id for acc in db_accounts}
                
                if pool_account_ids != db_account_ids:
                    print("Database accounts differ from pool manager, updating...")
                    # The pool manager will be updated on next restart
                    # For now, just log the difference
                    print(f"Pool accounts: {pool_account_ids}")
                    print(f"Database accounts: {db_account_ids}")
            
        except Exception as e:
            print(f"Error syncing with pool manager: {e}")
    
    @staticmethod
    async def update_account_activity(account_id: str):
        """Update account last activity timestamp"""
        try:
            result = db.google_drive_accounts.update_one(
                {"account_id": account_id},
                {
                    "$set": {
                        "last_activity": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            if result.modified_count > 0:
                print(f"Updated last activity for account {account_id}")
        except Exception as e:
            print(f"Error updating activity for account {account_id}: {e}")
    
    @staticmethod
    async def update_account_after_file_operation(account_id: str, file_size: int = 0):
        """Update account stats after file operation (upload/download)"""
        try:
            # Update last activity
            await GoogleDriveAccountService.update_account_activity(account_id)
            
            # Update files count and storage used (exclude deleted files)
            files_count = db.files.count_documents({
                "gdrive_account_id": account_id,
                "deleted_at": {"$exists": False}
            })
            
            # Calculate total storage used by this account (exclude deleted files)
            storage_result = db.files.aggregate([
                {"$match": {
                    "gdrive_account_id": account_id,
                    "deleted_at": {"$exists": False}
                }},
                {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
            ])
            storage_used = next(storage_result, {}).get("total_size", 0)
            
            # Update account in database
            db.google_drive_accounts.update_one(
                {"account_id": account_id},
                {
                    "$set": {
                        "files_count": files_count,
                        "storage_used": storage_used,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            print(f"Updated account {account_id} stats: {files_count} files, {storage_used} bytes")
            
        except Exception as e:
            print(f"Error updating account stats for {account_id}: {e}")
    
    @staticmethod
    async def create_account(account_data: GoogleDriveAccountCreate) -> GoogleDriveAccountDB:
        """Create a new Google Drive account"""
        await GoogleDriveAccountService._ensure_collection_exists()
        
        # Validate credentials with Google Drive API
        await GoogleDriveAccountService._validate_credentials(account_data)
        
        # Generate unique account ID
        account_id = f"account_{uuid.uuid4().hex[:8]}"
        
        # Parse service account data if provided
        service_account_data = {}
        if account_data.service_account_key:
            import json
            service_account_info = json.loads(account_data.service_account_key)
            service_account_data = {
                "private_key": service_account_info.get("private_key"),
                "private_key_id": service_account_info.get("private_key_id"),
                "project_id": service_account_info.get("project_id"),
            }
        
        # Create account document
        account_doc = GoogleDriveAccountDB(
            account_id=account_id,
            email=account_data.email,
            alias=account_data.alias,
            client_id=account_data.client_id,
            client_secret=account_data.client_secret,
            refresh_token=account_data.refresh_token,
            folder_id=account_data.folder_id,
            **service_account_data,
            is_active=True
        )
        
        # Insert into database (exclude _id field to let MongoDB auto-generate)
        insert_data = account_doc.dict(by_alias=True, exclude={"id"})
        result = db.google_drive_accounts.insert_one(insert_data)
        account_doc.id = result.inserted_id
        
        # Update storage quota and usage
        await GoogleDriveAccountService._update_account_quota(account_doc)
        
        return account_doc
    
    @staticmethod
    async def get_all_accounts() -> List[GoogleDriveAccountDB]:
        """Get all Google Drive accounts"""
        await GoogleDriveAccountService._ensure_collection_exists()
        
        accounts = []
        cursor = db.google_drive_accounts.find({})
        
        for doc in cursor:
            # Convert ObjectId to string for serialization
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            # Handle None values properly
            if doc.get("_id") == "None":
                doc["_id"] = None
            # Remove _id field to avoid Pydantic validation issues
            doc.pop("_id", None)
            # Create account object
            account = GoogleDriveAccountDB(**doc)
            accounts.append(account)
        
        # If no accounts in database, try to migrate from environment
        if not accounts:
            await GoogleDriveAccountService.migrate_env_accounts_to_db()
            # Try again after migration
            cursor = db.google_drive_accounts.find({})
            for doc in cursor:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                account = GoogleDriveAccountDB(**doc)
                accounts.append(account)
        
        return accounts
    
    @staticmethod
    async def get_account_by_id(account_id: str) -> Optional[GoogleDriveAccountDB]:
        """Get account by ID"""
        doc = db.google_drive_accounts.find_one({"account_id": account_id})
        if doc:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            # Handle None values properly
            if doc.get("_id") == "None":
                doc["_id"] = None
            # Remove _id field to avoid Pydantic validation issues
            doc.pop("_id", None)
            return GoogleDriveAccountDB(**doc)
        return None
    
    @staticmethod
    async def update_account(account_id: str, update_data: GoogleDriveAccountUpdate) -> Optional[GoogleDriveAccountDB]:
        """Update account information"""
        update_dict = update_data.dict(exclude_unset=True)
        update_dict["updated_at"] = datetime.utcnow()
        
        result = db.google_drive_accounts.update_one(
            {"account_id": account_id},
            {"$set": update_dict}
        )
        
        if result.modified_count > 0:
            return await GoogleDriveAccountService.get_account_by_id(account_id)
        return None
    
    @staticmethod
    async def delete_account(account_id: str, force: bool = False) -> bool:
        """Delete account"""
        # Check if account has files
        if not force:
            files_count = db.files.count_documents({"gdrive_account_id": account_id})
            if files_count > 0:
                raise ValueError(f"Account has {files_count} files. Use force=true to delete anyway.")
        
        result = db.google_drive_accounts.delete_one({"account_id": account_id})
        return result.deleted_count > 0
    
    @staticmethod
    async def toggle_account_status(account_id: str) -> Optional[GoogleDriveAccountDB]:
        """Toggle account active status"""
        account = await GoogleDriveAccountService.get_account_by_id(account_id)
        if not account:
            return None
        
        new_status = not account.is_active
        update_data = GoogleDriveAccountUpdate(is_active=new_status)
        
        return await GoogleDriveAccountService.update_account(account_id, update_data)
    
    @staticmethod
    async def update_account_quota(account_id: str) -> Optional[GoogleDriveAccountDB]:
        """Update account storage quota and usage from Google Drive API"""
        account = await GoogleDriveAccountService.get_account_by_id(account_id)
        if not account:
            return None
        
        await GoogleDriveAccountService._update_account_quota(account)
        return account
    
    @staticmethod
    async def update_all_accounts_quota() -> List[GoogleDriveAccountDB]:
        """Update quota for all accounts"""
        accounts = await GoogleDriveAccountService.get_all_accounts()
        updated_accounts = []
        
        for account in accounts:
            try:
                await GoogleDriveAccountService._update_account_quota(account)
                updated_accounts.append(account)
            except Exception as e:
                print(f"Error updating quota for account {account.account_id}: {e}")
        
        return updated_accounts
    
    @staticmethod
    async def get_account_statistics() -> Dict[str, Any]:
        """Get aggregated statistics for all accounts"""
        accounts = await GoogleDriveAccountService.get_all_accounts()
        
        total_accounts = len(accounts)
        active_accounts = len([acc for acc in accounts if acc.is_active])
        total_storage_used = sum(acc.storage_used for acc in accounts)
        total_storage_quota = sum(acc.storage_quota for acc in accounts)
        
        # Calculate average performance
        performance_scores = [acc.performance_score for acc in accounts if acc.performance_score > 0]
        average_performance = sum(performance_scores) / len(performance_scores) if performance_scores else 0
        
        return {
            "total_accounts": total_accounts,
            "active_accounts": active_accounts,
            "total_storage_used": total_storage_used,
            "total_storage_quota": total_storage_quota,
            "average_performance": average_performance
        }
    
    @staticmethod
    async def _validate_credentials(account_data: GoogleDriveAccountCreate) -> None:
        """Validate Google Drive credentials by making a test API call"""
        try:
            # Determine if this is a service account or OAuth 2.0
            if account_data.service_account_key:
                # Service account validation
                await GoogleDriveAccountService._validate_service_account(account_data)
            elif account_data.client_id and account_data.client_secret and account_data.refresh_token:
                # OAuth 2.0 validation
                await GoogleDriveAccountService._validate_oauth_credentials(account_data)
            else:
                raise ValueError("Either service_account_key or OAuth credentials (client_id, client_secret, refresh_token) must be provided")
                
        except Exception as e:
            raise ValueError(f"Credential validation failed: {str(e)}")
    
    @staticmethod
    async def _validate_service_account(account_data: GoogleDriveAccountCreate) -> None:
        """Validate service account credentials"""
        try:
            import json
            from google.oauth2 import service_account
            
            # Parse service account JSON
            service_account_info = json.loads(account_data.service_account_key)
            
            # Create service account credentials
            creds = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=SCOPES
            )
            
            # Build service
            service = build('drive', 'v3', credentials=creds, static_discovery=False)
            
            # Test API call - get about information
            about = service.about().get(fields="user,storageQuota").execute()
            
            # Validate service account email matches
            service_email = service_account_info.get('client_email', '')
            if service_email != account_data.email:
                raise ValueError(f"Email mismatch. Expected: {account_data.email}, Got: {service_email}")
                
        except json.JSONDecodeError:
            raise ValueError("Invalid service account JSON format")
        except HttpError as e:
            raise ValueError(f"Google Drive API error: {e.content}")
        except Exception as e:
            raise ValueError(f"Service account validation failed: {str(e)}")
    
    @staticmethod
    async def _validate_oauth_credentials(account_data: GoogleDriveAccountCreate) -> None:
        """Validate OAuth 2.0 credentials"""
        try:
            # Create credentials
            creds = Credentials.from_authorized_user_info(
                info={
                    "client_id": account_data.client_id,
                    "client_secret": account_data.client_secret,
                    "refresh_token": account_data.refresh_token,
                },
                scopes=SCOPES
            )
            
            # Build service
            service = build('drive', 'v3', credentials=creds, static_discovery=False)
            
            # Test API call - get about information
            about = service.about().get(fields="user,storageQuota").execute()
            
            # Validate user email matches
            user_email = about.get('user', {}).get('emailAddress', '')
            if user_email != account_data.email:
                raise ValueError(f"Email mismatch. Expected: {account_data.email}, Got: {user_email}")
                
        except HttpError as e:
            raise ValueError(f"Google Drive API error: {e.content}")
        except Exception as e:
            raise ValueError(f"OAuth validation failed: {str(e)}")
    
    @staticmethod
    async def _get_folder_path(service, folder_id: str) -> str:
        """Get the full path of a Google Drive folder"""
        try:
            path_parts = []
            current_id = folder_id
            
            while current_id:
                folder_info = service.files().get(
                    fileId=current_id,
                    fields="name,parents"
                ).execute()
                
                path_parts.insert(0, folder_info.get('name', 'Unknown'))
                parents = folder_info.get('parents', [])
                current_id = parents[0] if parents else None
            
            return '/'.join(path_parts) if path_parts else 'Root'
        except Exception as e:
            print(f"Error getting folder path for {folder_id}: {e}")
            return 'Unknown'
    
    @staticmethod
    async def _update_account_quota(account: GoogleDriveAccountDB) -> None:
        """Update account storage quota and usage from Google Drive API"""
        try:
            # Create credentials based on account type
            if account.private_key:
                # Service account
                from google.oauth2 import service_account
                service_account_info = {
                    "type": "service_account",
                    "project_id": account.project_id,
                    "private_key_id": account.private_key_id,
                    "private_key": account.private_key,
                    "client_email": account.email,
                    "client_id": account.client_id,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{account.email}",
                    "universe_domain": "googleapis.com"
                }
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES
                )
            else:
                # OAuth 2.0
                creds = Credentials.from_authorized_user_info(
                    info={
                        "client_id": account.client_id,
                        "client_secret": account.client_secret,
                        "refresh_token": account.refresh_token,
                    },
                    scopes=SCOPES
                )
            
            # Build service
            service = build('drive', 'v3', credentials=creds, static_discovery=False)
            
            # Get storage quota
            about = service.about().get(fields="storageQuota").execute()
            storage_quota = about.get('storageQuota', {})
            storage_quota_limit = int(storage_quota.get('limit', 0) or 0)
            
            # Get folder information if folder_id exists
            folder_name = None
            folder_path = None
            if account.folder_id:
                try:
                    folder_info = service.files().get(
                        fileId=account.folder_id,
                        fields="name,parents",
                        supportsAllDrives=True,
                    ).execute()
                    folder_name = folder_info.get('name')
                    
                    # Build folder path
                    folder_path = await GoogleDriveAccountService._get_folder_path(service, account.folder_id)
                except Exception as e:
                    print(f"Error fetching folder info for account {account.account_id}: {e}")
            
            # Get files count and total size - include shared files from other owners
            files_query = "trashed = false"
            if account.folder_id:
                # Use enhanced query to include shared files accessible to this account
                files_query = f"('{account.folder_id}' in parents or sharedWithMe) and trashed = false"

            # Comprehensive testing to identify why some files might not be visible
            try:
                # Test 1: Simple query to see total files visible to this account
                simple_result = service.files().list(
                    q="trashed = false",
                    fields="files(id)",
                    pageSize=1,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                
                # Test 2: Check if folder exists and get its metadata
                if account.folder_id:
                    try:
                        folder_metadata = service.files().get(
                            fileId=account.folder_id,
                            fields="id,name,permissions,parents,shared,owners",
                            supportsAllDrives=True
                        ).execute()
                    except Exception as e:
                        pass
                
                # Test 3: Try alternative queries to see if more files are visible
                if account.folder_id:
                    try:
                        # Query 1: Include files shared with me
                        shared_query = f"('{account.folder_id}' in parents or sharedWithMe) and trashed = false"
                        shared_result = service.files().list(
                            q=shared_query,
                            fields="files(id,name,owners,permissions)",
                            pageSize=20,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        ).execute()
                        shared_files = shared_result.get('files', [])
                        for i, file in enumerate(shared_files[:10]):  # Show first 10
                            owners = file.get('owners', [])
                            owner_emails = [owner.get('emailAddress', 'Unknown') for owner in owners]
                        
                        # Query 2: Search for all files in and around this folder
                        broad_query = f"('{account.folder_id}' in parents or parents in '{account.folder_id}') and trashed = false"
                        broad_result = service.files().list(
                            q=broad_query,
                            fields="files(id,name,parents,shared)",
                            pageSize=20,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        ).execute()
                        broad_files = broad_result.get('files', [])
                        
                        # Query 3: Check if this is a shared drive folder
                        about_result = service.about().get(fields="user").execute()
                        current_user = about_result.get('user', {}).get('emailAddress', 'Unknown')
                        
                    except Exception as e:
                        pass
                        
            except Exception as e:
                pass

            # Paginate through all files to compute accurate totals and counts
            next_page_token = None
            files_count = 0
            storage_used = 0
            page_num = 1
            
            
            while True:
                
                files_result = service.files().list(
                    q=files_query,
                    fields="nextPageToken, files(id,name,size,mimeType,parents)",  # Added name, mimeType, parents for debugging
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageToken=next_page_token
                ).execute()

                files = files_result.get('files', [])
                
                # OPTION: Count ALL accessible files vs only files in target folder
                # CURRENT: Only files physically in the target folder (parent = folder_id)
                # ALTERNATIVE: All files accessible to this account (remove this filter block)
                if account.folder_id:
                    filtered_files = []
                    for file in files:
                        file_parents = file.get('parents', [])
                        if account.folder_id in file_parents:
                            filtered_files.append(file)
                    
                    # Debug: Show what we're filtering
                    
                    # Show some filtered-out files for debugging
                    all_files = files_result.get('files', [])
                    filtered_out = [f for f in all_files if f not in filtered_files]
                    for i, file in enumerate(filtered_out[:3]):  # Show first 3 filtered-out files
                        parents = file.get('parents', [])
                        print(f"🔧 [DEBUG] {account.account_id}: Filtered OUT: {file.get('name')} (parents: {parents})")
                    
                    files = filtered_files
                
                page_files_count = len(files)
                page_storage_used = sum(int(f.get('size', 0)) for f in files)
                
                

                
                files_count += page_files_count
                storage_used += page_storage_used

                next_page_token = files_result.get('nextPageToken')
                if not next_page_token:
                    break
                
                page_num += 1
            
            
            # Use folder-level usage for clarity and controllability
            effective_storage_used = storage_used

            # Update account in database
            update_data = {
                "storage_quota": storage_quota_limit,
                "storage_used": effective_storage_used,
                "files_count": files_count,
                "folder_name": folder_name,
                "folder_path": folder_path,
                "last_quota_check": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Update health status based on quota usage
            if storage_quota_limit:
                usage_percentage = (effective_storage_used / storage_quota_limit) * 100
                if usage_percentage > 90:
                    update_data["health_status"] = "critical"
                elif usage_percentage > 80:
                    update_data["health_status"] = "warning"
                else:
                    update_data["health_status"] = "healthy"
            
            # Update database
            update_result = db.google_drive_accounts.update_one(
                {"account_id": account.account_id},
                {"$set": update_data}
            )
            
            # Update the account object
            account.storage_quota = storage_quota_limit
            account.storage_used = effective_storage_used
            account.files_count = files_count
            account.folder_name = folder_name
            account.folder_path = folder_path
            account.last_quota_check = datetime.utcnow()
            account.updated_at = datetime.utcnow()
            
        except Exception as e:
            print(f"Error updating quota for account {account.account_id}: {e}")
            # Update health status to error
            db.google_drive_accounts.update_one(
                {"account_id": account.account_id},
                {"$set": {
                    "health_status": "error",
                    "last_quota_check": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }}
            )

    @staticmethod
    async def delete_all_files_in_account_folder(account: GoogleDriveAccountDB) -> Dict[str, Any]:
        """Delete all files under the configured folder_id for a given account.
        Returns counts of deleted files and errors.
        """
        if not account.folder_id:
            return {"deleted": 0, "errors": 0, "message": "No folder_id configured; skipped"}
        try:
            # Create credentials based on account type
            if account.private_key:
                from google.oauth2 import service_account
                service_account_info = {
                    "type": "service_account",
                    "project_id": account.project_id,
                    "private_key_id": account.private_key_id,
                    "private_key": account.private_key,
                    "client_email": account.email,
                    "client_id": account.client_id,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{account.email}",
                    "universe_domain": "googleapis.com"
                }
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES
                )
            else:
                creds = Credentials.from_authorized_user_info(
                    info={
                        "client_id": account.client_id,
                        "client_secret": account.client_secret,
                        "refresh_token": account.refresh_token,
                    },
                    scopes=SCOPES
                )
            service = build('drive', 'v3', credentials=creds, static_discovery=False)
            deleted = 0
            errors = 0
            next_page_token = None
            query = f"'{account.folder_id}' in parents and trashed = false"
            while True:
                files_result = service.files().list(
                    q=query,
                    fields="nextPageToken, files(id)",
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageToken=next_page_token
                ).execute()
                files = files_result.get('files', [])
                for f in files:
                    fid = f.get('id')
                    try:
                        service.files().delete(fileId=fid, supportsAllDrives=True).execute()
                        deleted += 1
                    except Exception as de:
                        print(f"[GDRIVE_RESET] Failed to delete file {fid} in account {account.account_id}: {de}")
                        errors += 1
                next_page_token = files_result.get('nextPageToken')
                if not next_page_token:
                    break
            # After deletion, reset counters in DB and refresh quota
            db.google_drive_accounts.update_one(
                {"account_id": account.account_id},
                {"$set": {
                    "files_count": 0,
                    "storage_used": 0,
                    "updated_at": datetime.utcnow()
                }}
            )
            try:
                await GoogleDriveAccountService._update_account_quota(account)
            except Exception as qe:
                print(f"[GDRIVE_RESET] Quota refresh failed for {account.account_id}: {qe}")
            return {"deleted": deleted, "errors": errors}
        except Exception as e:
            print(f"[GDRIVE_RESET] Error deleting files for account {account.account_id}: {e}")
            return {"deleted": 0, "errors": 1, "message": str(e)}

    @staticmethod
    async def delete_all_files_all_accounts() -> Dict[str, Any]:
        """Delete all files under configured folders for all accounts in DB."""
        accounts = await GoogleDriveAccountService.get_all_accounts()
        total_deleted = 0
        total_errors = 0
        results = {}
        for acc in accounts:
            res = await GoogleDriveAccountService.delete_all_files_in_account_folder(acc)
            results[acc.account_id] = res
            total_deleted += res.get("deleted", 0)
            total_errors += res.get("errors", 0)
        return {"summary": {"deleted": total_deleted, "errors": total_errors}, "per_account": results}
    
    @staticmethod
    def format_storage_size(bytes_size: int) -> str:
        """Format storage size in human-readable format"""
        if bytes_size == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        while bytes_size >= 1024 and i < len(size_names) - 1:
            bytes_size /= 1024.0
            i += 1
        
        return f"{bytes_size:.1f} {size_names[i]}"
    
    @staticmethod
    def to_response_model(account: GoogleDriveAccountDB) -> GoogleDriveAccountResponse:
        """Convert database model to response model"""
        storage_percentage = (account.storage_used / account.storage_quota * 100) if account.storage_quota > 0 else 0
        
        return GoogleDriveAccountResponse(
            account_id=account.account_id,
            email=account.email,
            alias=account.alias,
            is_active=account.is_active,
            storage_used=account.storage_used,
            storage_quota=account.storage_quota,
            files_count=account.files_count,
            last_activity=account.last_activity,
            health_status=account.health_status,
            performance_score=account.performance_score,
            storage_used_formatted=GoogleDriveAccountService.format_storage_size(account.storage_used),
            storage_quota_formatted=GoogleDriveAccountService.format_storage_size(account.storage_quota),
            storage_percentage=storage_percentage,
            created_at=account.created_at,
            updated_at=account.updated_at,
            folder_id=account.folder_id,
            folder_name=account.folder_name,
            folder_path=account.folder_path
        ) 