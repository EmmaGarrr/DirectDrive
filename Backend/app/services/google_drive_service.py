# In file: Backend/app/services/google_drive_service.py

import asyncio
import io
import json
import time
from typing import AsyncGenerator, List, Dict, Optional
from collections import defaultdict
import threading

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# Re-importing MediaIoBaseDownload for the stable, official download method
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import settings, GoogleAccountConfig

SCOPES = ['https://www.googleapis.com/auth/drive']
REQUEST_LIMIT_PER_MINUTE = 500
DAILY_UPLOAD_LIMIT_BYTES = 740 * 1024 * 1024 * 1024

# --- All classes (ApiUsageTracker, GoogleDrivePoolManager) remain unchanged ---
class ApiUsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.requests = defaultdict(lambda: {"minute_timestamp": 0, "count": 0})
        self.uploads = defaultdict(lambda: {"day_timestamp": 0, "bytes": 0})
    def increment_request_count(self, account_id: str):
        with self._lock:
            current_minute = int(time.time() / 60)
            if self.requests[account_id]["minute_timestamp"] != current_minute:
                self.requests[account_id]["minute_timestamp"] = current_minute; self.requests[account_id]["count"] = 0
            self.requests[account_id]["count"] += 1
    def increment_upload_volume(self, account_id: str, file_size_bytes: int):
        with self._lock:
            current_day = int(time.time() / 86400)
            if self.uploads[account_id]["day_timestamp"] != current_day:
                self.uploads[account_id]["day_timestamp"] = current_day; self.uploads[account_id]["bytes"] = 0
            self.uploads[account_id]["bytes"] += file_size_bytes
    def get_usage(self, account_id: str) -> dict:
        with self._lock:
            current_minute = int(time.time() / 60); current_day = int(time.time() / 86400)
            req_count = self.requests[account_id]["count"] if self.requests[account_id]["minute_timestamp"] == current_minute else 0
            upload_bytes = self.uploads[account_id]["bytes"] if self.uploads[account_id]["day_timestamp"] == current_day else 0
            return {"requests_this_minute": req_count, "bytes_today": upload_bytes}
class GoogleDrivePoolManager:
    _instance = None; _lock = threading.Lock()
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance: cls._instance = super(GoogleDrivePoolManager, cls).__new__(cls)
        return cls._instance
    def __init__(self, accounts: List[GoogleAccountConfig]):
        if not hasattr(self, '_initialized'):
            self.accounts = accounts
            self.account_map: Dict[str, GoogleAccountConfig] = {acc.id: acc for acc in accounts}
            self.num_accounts = len(accounts); self.current_account_index = 0; self.tracker = ApiUsageTracker()
            self._async_lock = asyncio.Lock(); self._initialized = True
            if self.num_accounts > 0: print(f"[GDRIVE_POOL] Initialized with {self.num_accounts} accounts. Active account: {self.get_current_account().id}")
    async def reload_from_db(self) -> int:
        """Reload active Google Drive accounts from database into the pool."""
        try:
            from app.services.google_drive_account_service import GoogleDriveAccountService
            from app.core.config import GoogleAccountConfig
            # Fetch all accounts from DB
            db_accounts = await GoogleDriveAccountService.get_all_accounts()
            # Build a fresh list from active accounts that have OAuth creds
            refreshed: List[GoogleAccountConfig] = []
            for acc in db_accounts:
                if not acc.is_active:
                    continue
                if acc.client_id and acc.client_secret and acc.refresh_token:
                    refreshed.append(
                        GoogleAccountConfig(
                            id=acc.account_id,
                            client_id=acc.client_id,
                            client_secret=acc.client_secret,
                            refresh_token=acc.refresh_token,
                            folder_id=acc.folder_id,
                        )
                    )
            async with self._async_lock:
                self.accounts = refreshed
                self.account_map = {acc.id: acc for acc in refreshed}
                self.num_accounts = len(refreshed)
                self.current_account_index = 0
            print(f"[GDRIVE_POOL] Reloaded {self.num_accounts} active accounts from DB")
            return self.num_accounts
        except Exception as e:
            print(f"[GDRIVE_POOL] Failed to reload accounts from DB: {e}")
            return 0
    def get_current_account(self) -> Optional[GoogleAccountConfig]:
        if not self.accounts: return None
        return self.accounts[self.current_account_index]
    def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
        return self.account_map.get(account_id)
    async def get_active_account(self) -> Optional[GoogleAccountConfig]:
        """Select an active account using basic rate and health/quota gating."""
        # Ensure we have accounts; try to reload from DB if empty
        if self.num_accounts == 0:
            await self.reload_from_db()
            if self.num_accounts == 0:
                return None
        # Iterate through pool to find a suitable account
        for _ in range(self.num_accounts):
            async with self._async_lock:
                account = self.get_current_account()
                # Move pointer for next attempt regardless
                self.current_account_index = (self.current_account_index + 1) % self.num_accounts
            # Rate/quota per-minute/day checks
            usage = self.tracker.get_usage(account.id)
            if usage["requests_this_minute"] >= REQUEST_LIMIT_PER_MINUTE or usage["bytes_today"] >= DAILY_UPLOAD_LIMIT_BYTES:
                continue
            # DB-backed gating: is_active, health, and storage thresholds
            try:
                from app.db.mongodb import db
                doc = db.google_drive_accounts.find_one({"account_id": account.id})
                if not doc or not doc.get("is_active", False):
                    continue
                # Optional lightweight freshness check: skip if last_quota_check exists and usage > 95%
                storage_quota = int(doc.get("storage_quota", 0) or 0)
                storage_used = int(doc.get("storage_used", 0) or 0)
                if storage_quota > 0 and storage_used / max(storage_quota, 1) >= 0.95:
                    # Skip accounts near or over quota
                    continue
                health = (doc.get("health_status") or "unknown").lower()
                if health in ("critical", "error", "inactive"):
                    continue
            except Exception as e:
                print(f"[GDRIVE_POOL] Warning: DB gating error for {account.id}: {e}")
                # If gating fails, fall back to using the account
                pass
            # Passed all gates
            return account
        # No suitable account found
        return None
gdrive_pool_manager = GoogleDrivePoolManager(settings.GDRIVE_ACCOUNTS)

# --- The build() service object is smart enough to handle its own auth ---
def _get_gdrive_service(account: GoogleAccountConfig):
    creds = Credentials.from_authorized_user_info(info={"client_id": account.client_id, "client_secret": account.client_secret, "refresh_token": account.refresh_token}, scopes=SCOPES)
    # The build object automatically handles token refreshing for its requests
    return build('drive', 'v3', credentials=creds, static_discovery=False)

def _get_authed_session(account: GoogleAccountConfig) -> AuthorizedSession:
    creds = Credentials.from_authorized_user_info(info={"client_id": account.client_id, "client_secret": account.client_secret, "refresh_token": account.refresh_token}, scopes=SCOPES)
    return AuthorizedSession(creds)

def create_resumable_upload_session(filename: str, filesize: int, account: GoogleAccountConfig) -> str:
    # This function remains unchanged
    try:
        gdrive_pool_manager.tracker.increment_request_count(account.id)
        metadata = {'name': filename}
        if getattr(account, 'folder_id', None):
            metadata['parents'] = [account.folder_id]
        headers = {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(filesize)}
        authed_session = _get_authed_session(account)
        init_response = authed_session.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable', headers=headers, data=json.dumps(metadata))
        init_response.raise_for_status(); return init_response.headers['Location']
    except Exception as e:
        print(f"!!! [{account.id}] An unexpected error occurred in create_resumable_upload_session: {e}"); raise e

# --- FINAL FIX: RETURNING TO THE STABLE, OFFICIAL GOOGLE DOWNLOAD METHOD ---
async def async_stream_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> AsyncGenerator[bytes, None]:
    """
    Streams a file from Google Drive using the official, robust MediaIoBaseDownload
    method, which is resilient and avoids async conflicts.
    """
    try:
        gdrive_pool_manager.tracker.increment_request_count(account.id)
        # The service object, built with credentials, handles its own token refreshing.
        service = _get_gdrive_service(account)
        request = service.files().get_media(fileId=gdrive_id)
        
        # We use an in-memory buffer that the downloader writes to.
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while not done:
            # We run the blocking I/O call in a separate thread to not freeze the server.
            status, done = await asyncio.to_thread(downloader.next_chunk)
            
            # This safety check is still good practice.
            if status:
                fh.seek(0)
                yield fh.read()
                # Reset the buffer for the next chunk.
                fh.seek(0)
                fh.truncate(0)
            
        print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Finished streaming file {gdrive_id}")

    except HttpError as e:
        print(f"!!! [{account.id}] Google API error during stream: {e.content}"); raise e
    except Exception as e:
        print(f"!!! [{account.id}] Unexpected error during Google Drive stream: {e}"); raise e

async def delete_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> bool:
    """
    Delete a file from Google Drive using the API.
    Returns True if successful, False if file not found, raises exception for other errors.
    """
    try:
        gdrive_pool_manager.tracker.increment_request_count(account.id)
        service = _get_gdrive_service(account)
        
        # Use asyncio.to_thread to run the blocking API call
        def execute_delete():
            return service.files().delete(
                fileId=gdrive_id,
                supportsAllDrives=True
            ).execute()
        
        await asyncio.to_thread(execute_delete)
        
        print(f"[DELETE_GDRIVE] [{account.id}] Successfully deleted file {gdrive_id}")
        return True
        
    except HttpError as e:
        if e.resp.status == 404:
            print(f"[DELETE_GDRIVE] [{account.id}] File {gdrive_id} not found (404) - already deleted")
            return False
        else:
            print(f"!!! [{account.id}] Google API error during delete: {e.content}")
            raise e
    except Exception as e:
        print(f"!!! [{account.id}] Unexpected error during Google Drive delete: {e}")
        raise e