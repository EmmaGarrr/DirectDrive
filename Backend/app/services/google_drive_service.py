# # # # # # # In file: Backend/app/services/google_drive_service.py

# # # # # # import asyncio
# # # # # # import io
# # # # # # import json
# # # # # # import os
# # # # # # import threading
# # # # # # from typing import AsyncGenerator, Generator

# # # # # # from google.auth.transport.requests import AuthorizedSession
# # # # # # from google.oauth2.credentials import Credentials
# # # # # # from googleapiclient.discovery import build
# # # # # # from googleapiclient.errors import HttpError
# # # # # # from googleapiclient.http import MediaIoBaseDownload

# # # # # # from app.core.config import settings

# # # # # # SCOPES = ['https://www.googleapis.com/auth/drive']


# # # # # # # --- NEW: Standardized helper function for building an authenticated service client ---
# # # # # # def get_gdrive_service_for_user():
# # # # # #     """
# # # # # #     Builds a Google Drive service client consistently authenticated as the user
# # # # # #     using the stored OAuth 2.0 refresh token.
# # # # # #     """
# # # # # #     creds = Credentials.from_authorized_user_info(
# # # # # #         info={
# # # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # # #         },
# # # # # #         scopes=SCOPES
# # # # # #     )
# # # # # #     return build('drive', 'v3', credentials=creds)


# # # # # # # --- NEW: Standardized helper function for making direct HTTP requests ---
# # # # # # def get_authed_session_for_user():
# # # # # #     """
# # # # # #     Builds an authorized session object for making direct HTTP requests
# # # # # #     (like for resumable uploads) as the user.
# # # # # #     """
# # # # # #     creds = Credentials.from_authorized_user_info(
# # # # # #         info={
# # # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # # #         },
# # # # # #         scopes=SCOPES
# # # # # #     )
# # # # # #     return AuthorizedSession(creds)


# # # # # # # --- REWRITTEN and SIMPLIFIED ---
# # # # # # def create_resumable_upload_session(filename: str, filesize: int) -> str:
# # # # # #     """
# # # # # #     Initiates a resumable upload session with Google Drive and returns the session URL.
# # # # # #     This is now the recommended, direct method.
    
# # # # # #     Args:
# # # # # #         filename (str): The name of the file to be uploaded.
# # # # # #         filesize (int): The total size of the file in bytes.

# # # # # #     Returns:
# # # # # #         str: The unique, one-time-use URL for the resumable upload session.
# # # # # #     """
# # # # # #     try:
# # # # # #         # Step 1: Define the file's metadata (name and parent folder).
# # # # # #         metadata = {
# # # # # #             'name': filename,
# # # # # #             'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
# # # # # #         }
        
# # # # # #         # Step 2: Set up the headers for the initiation request.
# # # # # #         # We tell Google the type of the final content and, crucially, its total size.
# # # # # #         headers = {
# # # # # #             'Content-Type': 'application/json; charset=UTF-8',
# # # # # #             'X-Upload-Content-Type': 'application/octet-stream', # The type of the file data itself
# # # # # #             'X-Upload-Content-Length': str(filesize)
# # # # # #         }

# # # # # #         # Step 3: Get an authenticated session using our new helper function.
# # # # # #         authed_session = get_authed_session_for_user()
        
# # # # # #         print("[GDRIVE_SERVICE] Initiating resumable session...")
        
# # # # # #         # Step 4: Make the POST request to the resumable upload endpoint.
# # # # # #         init_response = authed_session.post(
# # # # # #             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
# # # # # #             headers=headers,
# # # # # #             data=json.dumps(metadata) # The body contains the metadata.
# # # # # #         )
# # # # # #         init_response.raise_for_status() # This will raise an error for non-2xx responses.
        
# # # # # #         # Step 5: Extract the unique upload URL from the response headers.
# # # # # #         upload_url = init_response.headers['Location']
# # # # # #         print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
# # # # # #         return upload_url

# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! A Google API HTTP Error occurred: {e.content}")
# # # # # #         raise e
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
# # # # # #         raise e

# # # # # # # # --- NEW FUNCTION TO BE ADDED ---
# # # # # # # def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
# # # # # # #     """
# # # # # # #     Yields a file from Google Drive in chunks of a specified size without loading
# # # # # # #     the whole file into memory. This is for the backend-to-backend transfer.
    
# # # # # # #     Args:
# # # # # # #         gdrive_id (str): The ID of the file on Google Drive.
# # # # # # #         chunk_size (int): The size of each chunk in bytes.

# # # # # # #     Yields:
# # # # # # #         bytes: A chunk of the file data.
# # # # # # #     """
# # # # # # #     try:
# # # # # # #         print(f"[GDRIVE_STREAMER] Starting chunked stream for GDrive ID: {gdrive_id}")
# # # # # # #         service = get_gdrive_service_for_user()
# # # # # # #         request = service.files().get_media(fileId=gdrive_id)
        
# # # # # # #         # Use a BytesIO buffer as a temporary holder for the stream downloader
# # # # # # #         fh = io.BytesIO()
# # # # # # #         downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
# # # # # # #         done = False
# # # # # # #         while not done:
# # # # # # #             status, done = downloader.next_chunk()
# # # # # # #             if status:
# # # # # # #                 print(f"[GDRIVE_STREAMER] Downloaded chunk progress: {int(status.progress() * 100)}%")
            
# # # # # # #             # Yield the downloaded chunk and clear the buffer for the next one
# # # # # # #             fh.seek(0)
# # # # # # #             yield fh.read()
# # # # # # #             fh.seek(0)
# # # # # # #             fh.truncate(0)
            
# # # # # # #         print(f"[GDRIVE_STREAMER] Finished chunked stream for {gdrive_id}.")

# # # # # # #     except Exception as e:
# # # # # # #         print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
# # # # # # #         raise e
    

# # # # # # async def stream_gdrive_file(file_id: str) -> AsyncGenerator[bytes, None]:
# # # # # #     """
# # # # # #     Asynchronously streams a file from Google Drive using a dedicated thread
# # # # # #     and an OS pipe to bridge the sync/async gap safely.
# # # # # #     """
# # # # # #     read_fd, write_fd = os.pipe()

# # # # # #     def download_in_thread():
# # # # # #         writer = None
# # # # # #         try:
# # # # # #             print("[DOWNLOAD_THREAD] Starting download...")
# # # # # #             service = get_gdrive_service_for_user() # Uses the new helper
# # # # # #             request = service.files().get_media(fileId=file_id)
# # # # # #             writer = io.FileIO(write_fd, 'wb')
# # # # # #             downloader = MediaIoBaseDownload(writer, request)
            
# # # # # #             done = False
# # # # # #             while not done:
# # # # # #                 status, done = downloader.next_chunk()
# # # # # #                 if status:
# # # # # #                     print(f"[DOWNLOAD_THREAD] Downloaded {int(status.progress() * 100)}%.")

# # # # # #             print("[DOWNLOAD_THREAD] Download finished.")
# # # # # #         except Exception as e:
# # # # # #             print(f"!!! [DOWNLOAD_THREAD] Error: {e}")
# # # # # #         finally:
# # # # # #             if writer:
# # # # # #                 writer.close()

# # # # # #     download_thread = threading.Thread(target=download_in_thread, daemon=True)
# # # # # #     download_thread.start()

# # # # # #     loop = asyncio.get_event_loop()
# # # # # #     reader = io.FileIO(read_fd, 'rb')
    
# # # # # #     while True:
# # # # # #         chunk = await loop.run_in_executor(None, reader.read, 4 * 1024 * 1024)
# # # # # #         if not chunk:
# # # # # #             break
# # # # # #         yield chunk
            
# # # # # #     print(f"[GDRIVE_SERVICE] Finished streaming file {file_id}")
# # # # # #     download_thread.join()
# # # # # #     reader.close()
    

# # # # # # def delete_file_with_refresh_token(file_id: str):
# # # # # #     """
# # # # # #     Deletes a file from Google Drive using a user's OAuth 2.0 refresh token.
# # # # # #     """
# # # # # #     try:
# # # # # #         print(f"[GDRIVE_DELETER] Attempting to delete file {file_id} using user credentials.")
# # # # # #         service = get_gdrive_service_for_user() # Uses the new helper
# # # # # #         service.files().delete(fileId=file_id).execute()
# # # # # #         print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")
        
    
# # # # # # def download_file_from_gdrive(gdrive_id: str) -> io.BytesIO:
# # # # # #     """
# # # # # #     Downloads a file from Google Drive into an in-memory BytesIO object.
# # # # # #     """
# # # # # #     try:
# # # # # #         print(f"[GDRIVE_DOWNLOADER] Downloading file {gdrive_id} using user credentials.")
# # # # # #         service = get_gdrive_service_for_user() # Uses the new helper
# # # # # #         request = service.files().get_media(fileId=gdrive_id)
# # # # # #         fh = io.BytesIO()
# # # # # #         downloader = MediaIoBaseDownload(fh, request)
        
# # # # # #         done = False
# # # # # #         while not done:
# # # # # #             status, done = downloader.next_chunk()
# # # # # #             print(f"[GDRIVE_DOWNLOADER] Download progress: {int(status.progress() * 100)}%.")
        
# # # # # #         fh.seek(0)
# # # # # #         print(f"[GDRIVE_DOWNLOADER] File {gdrive_id} downloaded successfully.")
# # # # # #         return fh
# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! [GDRIVE_DOWNLOADER] Google API HTTP Error during download: {e.content}")
# # # # # #         raise e
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! [GDRIVE_DOWNLOADER] An unexpected error occurred during download: {e}")
# # # # # #         raise e
    

# # # # # # # In file: Backend/app/services/google_drive_service.py

# # # # # # import asyncio
# # # # # # import io
# # # # # # import json
# # # # # # import os
# # # # # # import threading
# # # # # # from typing import AsyncGenerator, Generator

# # # # # # from google.auth.transport.requests import AuthorizedSession
# # # # # # from google.oauth2.credentials import Credentials
# # # # # # from googleapiclient.discovery import build
# # # # # # from googleapiclient.errors import HttpError
# # # # # # from googleapiclient.http import MediaIoBaseDownload

# # # # # # from app.core.config import settings

# # # # # # SCOPES = ['https://www.googleapis.com/auth/drive']

# # # # # # def get_gdrive_service_for_user():
# # # # # #     creds = Credentials.from_authorized_user_info(
# # # # # #         info={
# # # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # # #         },
# # # # # #         scopes=SCOPES
# # # # # #     )
# # # # # #     return build('drive', 'v3', credentials=creds)

# # # # # # def get_authed_session_for_user():
# # # # # #     creds = Credentials.from_authorized_user_info(
# # # # # #         info={
# # # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # # #         },
# # # # # #         scopes=SCOPES
# # # # # #     )
# # # # # #     return AuthorizedSession(creds)

# # # # # # def create_resumable_upload_session(filename: str, filesize: int) -> str:
# # # # # #     try:
# # # # # #         metadata = {
# # # # # #             'name': filename,
# # # # # #             'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
# # # # # #         }
# # # # # #         headers = {
# # # # # #             'Content-Type': 'application/json; charset=UTF-8',
# # # # # #             'X-Upload-Content-Type': 'application/octet-stream',
# # # # # #             'X-Upload-Content-Length': str(filesize)
# # # # # #         }
# # # # # #         authed_session = get_authed_session_for_user()
# # # # # #         print("[GDRIVE_SERVICE] Initiating resumable session...")
# # # # # #         init_response = authed_session.post(
# # # # # #             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
# # # # # #             headers=headers,
# # # # # #             data=json.dumps(metadata)
# # # # # #         )
# # # # # #         init_response.raise_for_status()
# # # # # #         upload_url = init_response.headers['Location']
# # # # # #         print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
# # # # # #         return upload_url
# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! A Google API HTTP Error occurred: {e.content}")
# # # # # #         raise e
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
# # # # # #         raise e


# # # # # # # --- THIS IS THE NEW STREAMING FUNCTION FOR THE BACKGROUND WORKER ---
# # # # # # def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
# # # # # #     """
# # # # # #     Yields a file from Google Drive in fixed-size chunks without loading the
# # # # # #     whole file into memory. This is for the synchronous Celery worker.
    
# # # # # #     Args:
# # # # # #         gdrive_id (str): The ID of the file on Google Drive.
# # # # # #         chunk_size (int): The size of each chunk in bytes.

# # # # # #     Yields:
# # # # # #         bytes: A chunk of the file data, with a size up to chunk_size.
# # # # # #     """
# # # # # #     try:
# # # # # #         print(f"[GDRIVE_STREAMER] Starting chunked stream for GDrive ID: {gdrive_id}")
# # # # # #         service = get_gdrive_service_for_user()
# # # # # #         request = service.files().get_media(fileId=gdrive_id)
        
# # # # # #         # This BytesIO buffer is a small, temporary holder for the downloader.
# # # # # #         # Its size will never exceed chunk_size.
# # # # # #         fh = io.BytesIO()
# # # # # #         downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
# # # # # #         done = False
# # # # # #         while not done:
# # # # # #             status, done = downloader.next_chunk()
# # # # # #             if status:
# # # # # #                 print(f"[GDRIVE_STREAMER] Streaming progress: {int(status.progress() * 100)}%")
            
# # # # # #             # After a chunk is downloaded into fh, yield its content and then clear fh.
# # # # # #             fh.seek(0)
# # # # # #             yield fh.read()
            
# # # # # #             # Reset the buffer for the next chunk download.
# # # # # #             fh.seek(0)
# # # # # #             fh.truncate(0)
            
# # # # # #         print(f"[GDRIVE_STREAMER] Finished chunked stream for {gdrive_id}.")

# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! [GDRIVE_STREAMER] A Google API error occurred: {e.content}")
# # # # # #         raise e
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
# # # # # #         raise e


# # # # # # # --- THIS FUNCTION IS FOR THE LIVE USER-FACING DOWNLOAD (NO CHANGE) ---
# # # # # # async def stream_gdrive_file(file_id: str) -> AsyncGenerator[bytes, None]:
# # # # # #     read_fd, write_fd = os.pipe()

# # # # # #     def download_in_thread():
# # # # # #         writer = None
# # # # # #         try:
# # # # # #             print("[DOWNLOAD_THREAD] Starting download...")
# # # # # #             service = get_gdrive_service_for_user()
# # # # # #             request = service.files().get_media(fileId=file_id)
# # # # # #             writer = io.FileIO(write_fd, 'wb')
# # # # # #             downloader = MediaIoBaseDownload(writer, request)
            
# # # # # #             done = False
# # # # # #             while not done:
# # # # # #                 status, done = downloader.next_chunk()
# # # # # #                 if status:
# # # # # #                     print(f"[DOWNLOAD_THREAD] Downloaded {int(status.progress() * 100)}%.")
# # # # # #             print("[DOWNLOAD_THREAD] Download finished.")
# # # # # #         except Exception as e:
# # # # # #             print(f"!!! [DOWNLOAD_THREAD] Error: {e}")
# # # # # #         finally:
# # # # # #             if writer:
# # # # # #                 writer.close()

# # # # # #     download_thread = threading.Thread(target=download_in_thread, daemon=True)
# # # # # #     download_thread.start()

# # # # # #     loop = asyncio.get_event_loop()
# # # # # #     reader = io.FileIO(read_fd, 'rb')
    
# # # # # #     while True:
# # # # # #         chunk = await loop.run_in_executor(None, reader.read, 4 * 1024 * 1024)
# # # # # #         if not chunk:
# # # # # #             break
# # # # # #         yield chunk
            
# # # # # #     print(f"[GDRIVE_SERVICE] Finished streaming file {file_id}")
# # # # # #     download_thread.join()
# # # # # #     reader.close()
    

# # # # # # def delete_file_with_refresh_token(file_id: str):
# # # # # #     try:
# # # # # #         print(f"[GDRIVE_DELETER] Attempting to delete file {file_id} using user credentials.")
# # # # # #         service = get_gdrive_service_for_user()
# # # # # #         service.files().delete(fileId=file_id).execute()
# # # # # #         print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
# # # # # #     except HttpError as e:
# # # # # #         print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
# # # # # #     except Exception as e:
# # # # # #         print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")
        
    
# # # # # # --- REMOVED: This function is obsolete and dangerous for large files. ---
# # # # # # def download_file_from_gdrive(gdrive_id: str) -> io.BytesIO:
# # # # # #     ...



# # # # # ###########################################################################################################

# # # # # # In file: Backend/app/services/google_drive_service.py

# # # # # import asyncio
# # # # # import io
# # # # # import json
# # # # # from typing import AsyncGenerator, Generator

# # # # # from google.auth.transport.requests import AuthorizedSession
# # # # # from google.oauth2.credentials import Credentials
# # # # # from googleapiclient.discovery import build
# # # # # from googleapiclient.errors import HttpError
# # # # # from googleapiclient.http import MediaIoBaseDownload

# # # # # from app.core.config import settings

# # # # # SCOPES = ['https://www.googleapis.com/auth/drive']

# # # # # def get_gdrive_service_for_user():
# # # # #     creds = Credentials.from_authorized_user_info(
# # # # #         info={
# # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # #         },
# # # # #         scopes=SCOPES
# # # # #     )
# # # # #     return build('drive', 'v3', credentials=creds)

# # # # # def get_authed_session_for_user():
# # # # #     creds = Credentials.from_authorized_user_info(
# # # # #         info={
# # # # #             "client_id": settings.OAUTH_CLIENT_ID,
# # # # #             "client_secret": settings.OAUTH_CLIENT_SECRET,
# # # # #             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
# # # # #         },
# # # # #         scopes=SCOPES
# # # # #     )
# # # # #     return AuthorizedSession(creds)

# # # # # def create_resumable_upload_session(filename: str, filesize: int) -> str:
# # # # #     try:
# # # # #         metadata = {
# # # # #             'name': filename,
# # # # #             'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
# # # # #         }
# # # # #         headers = {
# # # # #             'Content-Type': 'application/json; charset=UTF-8',
# # # # #             'X-Upload-Content-Type': 'application/octet-stream',
# # # # #             'X-Upload-Content-Length': str(filesize)
# # # # #         }
# # # # #         authed_session = get_authed_session_for_user()
# # # # #         print("[GDRIVE_SERVICE] Initiating resumable session...")
# # # # #         init_response = authed_session.post(
# # # # #             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
# # # # #             headers=headers,
# # # # #             data=json.dumps(metadata)
# # # # #         )
# # # # #         init_response.raise_for_status()
# # # # #         upload_url = init_response.headers['Location']
# # # # #         print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
# # # # #         return upload_url
# # # # #     except HttpError as e:
# # # # #         print(f"!!! A Google API HTTP Error occurred: {e.content}")
# # # # #         raise e
# # # # #     except Exception as e:
# # # # #         print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
# # # # #         raise e

# # # # # # --- This is the synchronous streamer for the Celery worker (no change needed) ---
# # # # # def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
# # # # #     """
# # # # #     Yields a file from Google Drive in fixed-size chunks. For synchronous workers.
# # # # #     """
# # # # #     try:
# # # # #         service = get_gdrive_service_for_user()
# # # # #         request = service.files().get_media(fileId=gdrive_id)
# # # # #         fh = io.BytesIO()
# # # # #         downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
# # # # #         done = False
# # # # #         while not done:
# # # # #             status, done = downloader.next_chunk()
# # # # #             if status:
# # # # #                 print(f"[GDRIVE_STREAMER] Celery streaming progress: {int(status.progress() * 100)}%")
# # # # #             fh.seek(0)
# # # # #             yield fh.read()
# # # # #             fh.seek(0)
# # # # #             fh.truncate(0)
# # # # #     except HttpError as e:
# # # # #         print(f"!!! [GDRIVE_STREAMER] A Google API error occurred: {e.content}")
# # # # #         raise e
# # # # #     except Exception as e:
# # # # #         print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
# # # # #         raise e

# # # # # ###################################################################################
# # # # # # --- NEW ROBUST ASYNC STREAMING FUNCTION FOR LIVE USER-FACING DOWNLOADS ---
# # # # # ###################################################################################
# # # # # async def async_stream_gdrive_file(gdrive_id: str) -> AsyncGenerator[bytes, None]:
# # # # #     """
# # # # #     Asynchronously streams a file from Google Drive.

# # # # #     This is the modern, robust replacement for the old thread-based approach.
# # # # #     It uses asyncio.to_thread to run the blocking GDrive library calls in a
# # # # #     non-blocking way, making it safe and efficient for FastAPI.
# # # # #     """
# # # # #     try:
# # # # #         service = get_gdrive_service_for_user()
# # # # #         request = service.files().get_media(fileId=gdrive_id)
        
# # # # #         # Use an in-memory binary stream as a buffer for chunks.
# # # # #         fh = io.BytesIO()
# # # # #         downloader = MediaIoBaseDownload(fh, request)
        
# # # # #         done = False
# # # # #         while not done:
# # # # #             # Run the blocking downloader.next_chunk() in a separate thread
# # # # #             # managed by asyncio, and await its completion.
# # # # #             status, done = await asyncio.to_thread(downloader.next_chunk)

# # # # #             if status:
# # # # #                 print(f"[ASYNC_GDRIVE_DOWNLOAD] Downloaded {int(status.progress() * 100)}%.")

# # # # #             # Yield the content of the buffer and then clear it
# # # # #             fh.seek(0)
# # # # #             yield fh.read()
# # # # #             fh.seek(0)
# # # # #             fh.truncate(0)
            
# # # # #         print(f"[ASYNC_GDRIVE_DOWNLOAD] Finished streaming file {gdrive_id}")

# # # # #     except HttpError as e:
# # # # #         # This will catch API errors, e.g., if the file was deleted from Drive.
# # # # #         print(f"!!! [ASYNC_GDRIVE_DOWNLOAD] Google API error: {e.content}")
# # # # #         raise e
# # # # #     except Exception as e:
# # # # #         print(f"!!! [ASYNC_GDRIVE_DOWNLOAD] Unexpected error during stream: {e}")
# # # # #         raise e


# # # # # def delete_file_with_refresh_token(file_id: str):
# # # # #     try:
# # # # #         service = get_gdrive_service_for_user()
# # # # #         service.files().delete(fileId=file_id).execute()
# # # # #         print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
# # # # #     except HttpError as e:
# # # # #         print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
# # # # #     except Exception as e:
# # # # #         print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")




# # # # # In file: Backend/app/services/google_drive_service.py

# # # # import asyncio
# # # # import io
# # # # import json
# # # # import time
# # # # from typing import AsyncGenerator, Generator, List, Dict, Optional
# # # # from collections import defaultdict
# # # # import threading

# # # # from google.auth.transport.requests import AuthorizedSession
# # # # from google.oauth2.credentials import Credentials
# # # # from googleapiclient.discovery import build
# # # # from googleapiclient.errors import HttpError
# # # # from googleapiclient.http import MediaIoBaseDownload

# # # # from app.core.config import settings, GoogleAccountConfig

# # # # SCOPES = ['https://www.googleapis.com/auth/drive']

# # # # # --- NEW: CONFIGURABLE LIMITS ---
# # # # # We switch accounts when requests in the current minute exceed this number.
# # # # # Set lower than the actual limit (12000/min) to be safe.



# # # # REQUEST_LIMIT_PER_MINUTE = 500
# # # # # Daily upload limit in bytes (750 GB). We'll switch when we get close.
# # # # DAILY_UPLOAD_LIMIT_BYTES = 740 * 1024 * 1024 * 1024 # 740 GB to be safe


# # # # class ApiUsageTracker:
# # # #     """A thread-safe class to track API usage for multiple Google accounts."""
# # # #     def __init__(self):
# # # #         self._lock = threading.Lock()
# # # #         # Tracks requests per minute: { "account_1": {"minute_timestamp": 120, "count": 120} }
# # # #         self.requests = defaultdict(lambda: {"minute_timestamp": 0, "count": 0})
# # # #         # Tracks daily upload volume: { "account_1": {"day_timestamp": 45, "bytes": 12345} }
# # # #         self.uploads = defaultdict(lambda: {"day_timestamp": 0, "bytes": 0})

# # # #     def increment_request_count(self, account_id: str):
# # # #         with self._lock:
# # # #             current_minute = int(time.time() / 60)
# # # #             if self.requests[account_id]["minute_timestamp"] != current_minute:
# # # #                 # New minute, reset counter
# # # #                 self.requests[account_id]["minute_timestamp"] = current_minute
# # # #                 self.requests[account_id]["count"] = 0
# # # #             self.requests[account_id]["count"] += 1

# # # #     def increment_upload_volume(self, account_id: str, file_size_bytes: int):
# # # #         with self._lock:
# # # #             current_day = int(time.time() / 86400)
# # # #             if self.uploads[account_id]["day_timestamp"] != current_day:
# # # #                 # New day, reset counter
# # # #                 self.uploads[account_id]["day_timestamp"] = current_day
# # # #                 self.uploads[account_id]["bytes"] = 0
# # # #             self.uploads[account_id]["bytes"] += file_size_bytes

# # # #     def get_usage(self, account_id: str) -> dict:
# # # #         with self._lock:
# # # #             current_minute = int(time.time() / 60)
# # # #             current_day = int(time.time() / 86400)
            
# # # #             req_count = self.requests[account_id]["count"] if self.requests[account_id]["minute_timestamp"] == current_minute else 0
# # # #             upload_bytes = self.uploads[account_id]["bytes"] if self.uploads[account_id]["day_timestamp"] == current_day else 0
            
# # # #             return {"requests_this_minute": req_count, "bytes_today": upload_bytes}


# # # # class GoogleDrivePoolManager:
# # # #     """Manages a pool of Google Drive accounts and handles rotation."""
# # # #     _instance = None
# # # #     _lock = threading.Lock()

# # # #     def __new__(cls, *args, **kwargs):
# # # #         if not cls._instance:
# # # #             with cls._lock:
# # # #                 if not cls._instance:
# # # #                     cls._instance = super(GoogleDrivePoolManager, cls).__new__(cls)
# # # #         return cls._instance

# # # #     def __init__(self, accounts: List[GoogleAccountConfig]):
# # # #         if not hasattr(self, '_initialized'): # Prevent re-initialization
# # # #             self.accounts = accounts
# # # #             self.account_map: Dict[str, GoogleAccountConfig] = {acc.id: acc for acc in accounts}
# # # #             self.num_accounts = len(accounts)
# # # #             self.current_account_index = 0
# # # #             self.tracker = ApiUsageTracker()
# # # #             self._async_lock = asyncio.Lock()
# # # #             self._initialized = True
# # # #             if self.num_accounts > 0:
# # # #                 print(f"[GDRIVE_POOL] Initialized with {self.num_accounts} accounts. Active account: {self.get_current_account().id}")

# # # #     def get_current_account(self) -> Optional[GoogleAccountConfig]:
# # # #         if not self.accounts:
# # # #             return None
# # # #         return self.accounts[self.current_account_index]
        
# # # #     def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
# # # #         return self.account_map.get(account_id)

# # # #     async def get_active_account(self) -> Optional[GoogleAccountConfig]:
# # # #         """The core logic: finds a healthy account, rotating if necessary."""
# # # #         if self.num_accounts == 0:
# # # #             return None

# # # #         async with self._async_lock:
# # # #             for _ in range(self.num_accounts):
# # # #                 account = self.get_current_account()
# # # #                 usage = self.tracker.get_usage(account.id)

# # # #                 is_request_limit_ok = usage["requests_this_minute"] < REQUEST_LIMIT_PER_MINUTE
# # # #                 is_upload_limit_ok = usage["bytes_today"] < DAILY_UPLOAD_LIMIT_BYTES

# # # #                 if is_request_limit_ok and is_upload_limit_ok:
# # # #                     print(f"[GDRIVE_POOL] Using active account: {account.id} (Requests: {usage['requests_this_minute']}, Uploaded: {usage['bytes_today'] / (1024**3):.2f} GB)")
# # # #                     return account
                
# # # #                 # If limits are reached, rotate to the next account
# # # #                 print(f"[GDRIVE_POOL] WARNING: Account {account.id} has reached its limit. Rotating to next account.")
# # # #                 self.current_account_index = (self.current_account_index + 1) % self.num_accounts
            
# # # #             # If we loop through all accounts and none are available
# # # #             print("[GDRIVE_POOL] CRITICAL: All Google Drive accounts have reached their API limits.")
# # # #             return None

# # # # # --- SINGLETON INSTANCE ---
# # # # gdrive_pool_manager = GoogleDrivePoolManager(settings.GDRIVE_ACCOUNTS)


# # # # # --- MODIFIED HELPER FUNCTIONS ---
# # # # # These functions now take a 'GoogleAccountConfig' object to work with a specific account.

# # # # def _get_gdrive_service(account: GoogleAccountConfig):
# # # #     creds = Credentials.from_authorized_user_info(
# # # #         info={
# # # #             "client_id": account.client_id,
# # # #             "client_secret": account.client_secret,
# # # #             "refresh_token": account.refresh_token,
# # # #         },
# # # #         scopes=SCOPES
# # # #     )
# # # #     return build('drive', 'v3', credentials=creds)

# # # # def _get_authed_session(account: GoogleAccountConfig):
# # # #     creds = Credentials.from_authorized_user_info(
# # # #         info={
# # # #             "client_id": account.client_id,
# # # #             "client_secret": account.client_secret,
# # # #             "refresh_token": account.refresh_token,
# # # #         },
# # # #         scopes=SCOPES
# # # #     )
# # # #     return AuthorizedSession(creds)

# # # # def create_resumable_upload_session(filename: str, filesize: int, account: GoogleAccountConfig) -> str:
# # # #     try:
# # # #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# # # #         metadata = {
# # # #             'name': filename,
# # # #             'parents': [account.folder_id]
# # # #         }
# # # #         headers = {
# # # #             'Content-Type': 'application/json; charset=UTF-8',
# # # #             'X-Upload-Content-Type': 'application/octet-stream',
# # # #             'X-Upload-Content-Length': str(filesize)
# # # #         }
# # # #         authed_session = _get_authed_session(account)
# # # #         print(f"[GDRIVE_SERVICE] [{account.id}] Initiating resumable session...")
# # # #         init_response = authed_session.post(
# # # #             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
# # # #             headers=headers,
# # # #             data=json.dumps(metadata)
# # # #         )
# # # #         init_response.raise_for_status()
# # # #         upload_url = init_response.headers['Location']
# # # #         print(f"[GDRIVE_SERVICE] [{account.id}] Session initiated successfully.")
# # # #         return upload_url
# # # #     except HttpError as e:
# # # #         print(f"!!! [{account.id}] A Google API HTTP Error occurred: {e.content}")
# # # #         raise e
# # # #     except Exception as e:
# # # #         print(f"!!! [{account.id}] An unexpected error occurred in create_resumable_upload_session: {e}")
# # # #         raise e

# # # # async def async_stream_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> AsyncGenerator[bytes, None]:
# # # #     try:
# # # #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# # # #         service = _get_gdrive_service(account)
# # # #         request = service.files().get_media(fileId=gdrive_id)
        
# # # #         fh = io.BytesIO()
# # # #         downloader = MediaIoBaseDownload(fh, request)
        
# # # #         done = False
# # # #         while not done:
# # # #             status, done = await asyncio.to_thread(downloader.next_chunk)
# # # #             if status:
# # # #                 print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Downloaded {int(status.progress() * 100)}%.")
# # # #             fh.seek(0)
# # # #             yield fh.read()
# # # #             fh.seek(0)
# # # #             fh.truncate(0)
            
# # # #         print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Finished streaming file {gdrive_id}")

# # # #     except HttpError as e:
# # # #         print(f"!!! [{account.id}] Google API error during stream: {e.content}")
# # # #         raise e
# # # #     except Exception as e:
# # # #         print(f"!!! [{account.id}] Unexpected error during stream: {e}")
# # # #         raise e




# # # # In file: Backend/app/services/google_drive_service.py

# # # import asyncio
# # # import io
# # # import json
# # # import time
# # # from typing import AsyncGenerator, Generator, List, Dict, Optional
# # # from collections import defaultdict
# # # import threading

# # # from google.auth.transport.requests import AuthorizedSession
# # # from google.oauth2.credentials import Credentials
# # # from googleapiclient.discovery import build
# # # from googleapiclient.errors import HttpError
# # # from googleapiclient.http import MediaIoBaseDownload

# # # from app.core.config import settings, GoogleAccountConfig

# # # SCOPES = ['https://www.googleapis.com/auth/drive']

# # # # --- CONFIGURABLE LIMITS ---
# # # REQUEST_LIMIT_PER_MINUTE = 500
# # # DAILY_UPLOAD_LIMIT_BYTES = 740 * 1024 * 1024 * 1024 # 740 GB to be safe

# # # class ApiUsageTracker:
# # #     def __init__(self):
# # #         self._lock = threading.Lock()
# # #         self.requests = defaultdict(lambda: {"minute_timestamp": 0, "count": 0})
# # #         self.uploads = defaultdict(lambda: {"day_timestamp": 0, "bytes": 0})

# # #     def increment_request_count(self, account_id: str):
# # #         with self._lock:
# # #             current_minute = int(time.time() / 60)
# # #             if self.requests[account_id]["minute_timestamp"] != current_minute:
# # #                 self.requests[account_id]["minute_timestamp"] = current_minute
# # #                 self.requests[account_id]["count"] = 0
# # #             self.requests[account_id]["count"] += 1

# # #     def increment_upload_volume(self, account_id: str, file_size_bytes: int):
# # #         with self._lock:
# # #             current_day = int(time.time() / 86400)
# # #             if self.uploads[account_id]["day_timestamp"] != current_day:
# # #                 self.uploads[account_id]["day_timestamp"] = current_day
# # #                 self.uploads[account_id]["bytes"] = 0
# # #             self.uploads[account_id]["bytes"] += file_size_bytes

# # #     def get_usage(self, account_id: str) -> dict:
# # #         with self._lock:
# # #             current_minute = int(time.time() / 60)
# # #             current_day = int(time.time() / 86400)
# # #             req_count = self.requests[account_id]["count"] if self.requests[account_id]["minute_timestamp"] == current_minute else 0
# # #             upload_bytes = self.uploads[account_id]["bytes"] if self.uploads[account_id]["day_timestamp"] == current_day else 0
# # #             return {"requests_this_minute": req_count, "bytes_today": upload_bytes}

# # # class GoogleDrivePoolManager:
# # #     _instance = None
# # #     _lock = threading.Lock()

# # #     def __new__(cls, *args, **kwargs):
# # #         if not cls._instance:
# # #             with cls._lock:
# # #                 if not cls._instance:
# # #                     cls._instance = super(GoogleDrivePoolManager, cls).__new__(cls)
# # #         return cls._instance

# # #     def __init__(self, accounts: List[GoogleAccountConfig]):
# # #         if not hasattr(self, '_initialized'):
# # #             self.accounts = accounts
# # #             self.account_map: Dict[str, GoogleAccountConfig] = {acc.id: acc for acc in accounts}
# # #             self.num_accounts = len(accounts)
# # #             self.current_account_index = 0
# # #             self.tracker = ApiUsageTracker()
# # #             self._async_lock = asyncio.Lock()
# # #             self._initialized = True
# # #             if self.num_accounts > 0:
# # #                 print(f"[GDRIVE_POOL] Initialized with {self.num_accounts} accounts. Active account: {self.get_current_account().id}")

# # #     def get_current_account(self) -> Optional[GoogleAccountConfig]:
# # #         if not self.accounts: return None
# # #         return self.accounts[self.current_account_index]
        
# # #     def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
# # #         return self.account_map.get(account_id)

# # #     async def get_active_account(self) -> Optional[GoogleAccountConfig]:
# # #         if self.num_accounts == 0: return None
# # #         async with self._async_lock:
# # #             for _ in range(self.num_accounts):
# # #                 account = self.get_current_account()
# # #                 usage = self.tracker.get_usage(account.id)
# # #                 is_request_limit_ok = usage["requests_this_minute"] < REQUEST_LIMIT_PER_MINUTE
# # #                 is_upload_limit_ok = usage["bytes_today"] < DAILY_UPLOAD_LIMIT_BYTES
# # #                 if is_request_limit_ok and is_upload_limit_ok:
# # #                     print(f"[GDRIVE_POOL] Using active account: {account.id} (Requests: {usage['requests_this_minute']}, Uploaded: {usage['bytes_today'] / (1024**3):.2f} GB)")
# # #                     return account
# # #                 print(f"[GDRIVE_POOL] WARNING: Account {account.id} has reached its limit. Rotating to next account.")
# # #                 self.current_account_index = (self.current_account_index + 1) % self.num_accounts
# # #             print("[GDRIVE_POOL] CRITICAL: All Google Drive accounts have reached their API limits.")
# # #             return None

# # # gdrive_pool_manager = GoogleDrivePoolManager(settings.GDRIVE_ACCOUNTS)

# # # def _get_gdrive_service(account: GoogleAccountConfig):
# # #     creds = Credentials.from_authorized_user_info(info={"client_id": account.client_id, "client_secret": account.client_secret, "refresh_token": account.refresh_token}, scopes=SCOPES)
# # #     return build('drive', 'v3', credentials=creds)

# # # def _get_authed_session(account: GoogleAccountConfig):
# # #     creds = Credentials.from_authorized_user_info(info={"client_id": account.client_id, "client_secret": account.client_secret, "refresh_token": account.refresh_token}, scopes=SCOPES)
# # #     return AuthorizedSession(creds)

# # # def create_resumable_upload_session(filename: str, filesize: int, account: GoogleAccountConfig) -> str:
# # #     try:
# # #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# # #         metadata = {'name': filename, 'parents': [account.folder_id]}
# # #         headers = {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(filesize)}
# # #         authed_session = _get_authed_session(account)
# # #         print(f"[GDRIVE_SERVICE] [{account.id}] Initiating resumable session...")
# # #         init_response = authed_session.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable', headers=headers, data=json.dumps(metadata))
# # #         init_response.raise_for_status()
# # #         upload_url = init_response.headers['Location']
# # #         print(f"[GDRIVE_SERVICE] [{account.id}] Session initiated successfully.")
# # #         return upload_url
# # #     except HttpError as e:
# # #         print(f"!!! [{account.id}] A Google API HTTP Error occurred: {e.content}")
# # #         raise e
# # #     except Exception as e:
# # #         print(f"!!! [{account.id}] An unexpected error occurred in create_resumable_upload_session: {e}")
# # #         raise e

# # # async def async_stream_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> AsyncGenerator[bytes, None]:
# # #     try:
# # #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# # #         service = _get_gdrive_service(account)
# # #         request = service.files().get_media(fileId=gdrive_id)
        
# # #         fh = io.BytesIO()
# # #         downloader = MediaIoBaseDownload(fh, request)
        
# # #         done = False
# # #         while not done:
# # #             status, done = await asyncio.to_thread(downloader.next_chunk)
            
# # #             # --- THIS IS THE FIX ---
# # #             # Only process and yield data if we received a valid status update.
# # #             # This prevents yielding None or stale data on the final loop iteration.
# # #             if status:
# # #                 # print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Downloaded {int(status.progress() * 100)}%.")
# # #                 fh.seek(0)
# # #                 yield fh.read()
# # #                 fh.seek(0)
# # #                 fh.truncate(0)
# # #             # --- END OF FIX ---
            
# # #         print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Finished streaming file {gdrive_id}")

# # #     except HttpError as e:
# # #         print(f"!!! [{account.id}] Google API error during stream: {e.content}")
# # #         raise e
# # #     except Exception as e:
# # #         print(f"!!! [{account.id}] Unexpected error during stream: {e}")
# # #         raise e





# # # In file: Backend/app/services/google_drive_service.py

# # import asyncio
# # import io
# # import json
# # import time
# # from typing import AsyncGenerator, List, Dict, Optional
# # from collections import defaultdict
# # import threading

# # from google.auth.transport.requests import AuthorizedSession
# # from google.oauth2.credentials import Credentials
# # from googleapiclient.discovery import build
# # from googleapiclient.errors import HttpError
# # # MediaIoBaseDownload is no longer needed for the new resilient download method

# # from app.core.config import settings, GoogleAccountConfig

# # SCOPES = ['https://www.googleapis.com/auth/drive']
# # REQUEST_LIMIT_PER_MINUTE = 500
# # DAILY_UPLOAD_LIMIT_BYTES = 740 * 1024 * 1024 * 1024

# # class ApiUsageTracker:
# #     # ... (This class remains unchanged) ...
# #     def __init__(self):
# #         self._lock = threading.Lock()
# #         self.requests = defaultdict(lambda: {"minute_timestamp": 0, "count": 0})
# #         self.uploads = defaultdict(lambda: {"day_timestamp": 0, "bytes": 0})

# #     def increment_request_count(self, account_id: str):
# #         with self._lock:
# #             current_minute = int(time.time() / 60)
# #             if self.requests[account_id]["minute_timestamp"] != current_minute:
# #                 self.requests[account_id]["minute_timestamp"] = current_minute
# #                 self.requests[account_id]["count"] = 0
# #             self.requests[account_id]["count"] += 1

# #     def increment_upload_volume(self, account_id: str, file_size_bytes: int):
# #         with self._lock:
# #             current_day = int(time.time() / 86400)
# #             if self.uploads[account_id]["day_timestamp"] != current_day:
# #                 self.uploads[account_id]["day_timestamp"] = current_day
# #                 self.uploads[account_id]["bytes"] = 0
# #             self.uploads[account_id]["bytes"] += file_size_bytes

# #     def get_usage(self, account_id: str) -> dict:
# #         with self._lock:
# #             current_minute = int(time.time() / 60)
# #             current_day = int(time.time() / 86400)
# #             req_count = self.requests[account_id]["count"] if self.requests[account_id]["minute_timestamp"] == current_minute else 0
# #             upload_bytes = self.uploads[account_id]["bytes"] if self.uploads[account_id]["day_timestamp"] == current_day else 0
# #             return {"requests_this_minute": req_count, "bytes_today": upload_bytes}

# # class GoogleDrivePoolManager:
# #     # ... (This class remains unchanged) ...
# #     _instance = None
# #     _lock = threading.Lock()

# #     def __new__(cls, *args, **kwargs):
# #         if not cls._instance:
# #             with cls._lock:
# #                 if not cls._instance:
# #                     cls._instance = super(GoogleDrivePoolManager, cls).__new__(cls)
# #         return cls._instance

# #     def __init__(self, accounts: List[GoogleAccountConfig]):
# #         if not hasattr(self, '_initialized'):
# #             self.accounts = accounts
# #             self.account_map: Dict[str, GoogleAccountConfig] = {acc.id: acc for acc in accounts}
# #             self.num_accounts = len(accounts)
# #             self.current_account_index = 0
# #             self.tracker = ApiUsageTracker()
# #             self._async_lock = asyncio.Lock()
# #             self._initialized = True
# #             if self.num_accounts > 0:
# #                 print(f"[GDRIVE_POOL] Initialized with {self.num_accounts} accounts. Active account: {self.get_current_account().id}")

# #     def get_current_account(self) -> Optional[GoogleAccountConfig]:
# #         if not self.accounts: return None
# #         return self.accounts[self.current_account_index]
        
# #     def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
# #         return self.account_map.get(account_id)

# #     async def get_active_account(self) -> Optional[GoogleAccountConfig]:
# #         if self.num_accounts == 0: return None
# #         async with self._async_lock:
# #             for _ in range(self.num_accounts):
# #                 account = self.get_current_account()
# #                 usage = self.tracker.get_usage(account.id)
# #                 is_request_limit_ok = usage["requests_this_minute"] < REQUEST_LIMIT_PER_MINUTE
# #                 is_upload_limit_ok = usage["bytes_today"] < DAILY_UPLOAD_LIMIT_BYTES
# #                 if is_request_limit_ok and is_upload_limit_ok:
# #                     print(f"[GDRIVE_POOL] Using active account: {account.id} (Requests: {usage['requests_this_minute']}, Uploaded: {usage['bytes_today'] / (1024**3):.2f} GB)")
# #                     return account
# #                 print(f"[GDRIVE_POOL] WARNING: Account {account.id} has reached its limit. Rotating to next account.")
# #                 self.current_account_index = (self.current_account_index + 1) % self.num_accounts
# #             print("[GDRIVE_POOL] CRITICAL: All Google Drive accounts have reached their API limits.")
# #             return None

# # gdrive_pool_manager = GoogleDrivePoolManager(settings.GDRIVE_ACCOUNTS)

# # # Helper function to get a "smart" session that auto-refreshes tokens
# # def _get_authed_session(account: GoogleAccountConfig) -> AuthorizedSession:
# #     creds = Credentials.from_authorized_user_info(
# #         info={
# #             "client_id": account.client_id,
# #             "client_secret": account.client_secret,
# #             "refresh_token": account.refresh_token,
# #         },
# #         scopes=SCOPES
# #     )
# #     return AuthorizedSession(creds)

# # def create_resumable_upload_session(filename: str, filesize: int, account: GoogleAccountConfig) -> str:
# #     # ... (This function remains unchanged) ...
# #     try:
# #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# #         metadata = {'name': filename, 'parents': [account.folder_id]}
# #         headers = {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(filesize)}
# #         authed_session = _get_authed_session(account)
# #         print(f"[GDRIVE_SERVICE] [{account.id}] Initiating resumable session...")
# #         init_response = authed_session.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable', headers=headers, data=json.dumps(metadata))
# #         init_response.raise_for_status()
# #         upload_url = init_response.headers['Location']
# #         print(f"[GDRIVE_SERVICE] [{account.id}] Session initiated successfully.")
# #         return upload_url
# #     except HttpError as e:
# #         print(f"!!! [{account.id}] A Google API HTTP Error occurred: {e.content}")
# #         raise e
# #     except Exception as e:
# #         print(f"!!! [{account.id}] An unexpected error occurred in create_resumable_upload_session: {e}")
# #         raise e

# # # --- FINAL FIX: REWRITTEN DOWNLOAD FUNCTION ---
# # async def async_stream_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> AsyncGenerator[bytes, None]:
# #     """
# #     Streams a file from Google Drive using a resilient, auto-refreshing
# #     authorized session, making it suitable for very large files and long transfers.
# #     """
# #     # Construct the direct download URL for the Drive API
# #     url = f"https://www.googleapis.com/drive/v3/files/{gdrive_id}?alt=media"
    
# #     # Get a "smart" session that will handle token refreshing automatically
# #     authed_session = _get_authed_session(account)
    
# #     # We use httpx to make the async streaming request, using the authenticated session
# #     # from Google's library to sign the request.
# #     import httpx

# #     try:
# #         gdrive_pool_manager.tracker.increment_request_count(account.id)
# #         async with httpx.AsyncClient() as client:
# #             # We must manually add the authorization header before each request.
# #             # The session object knows how to refresh the token if needed.
# #             authed_session.refresh(httpx.Request("GET", url))
# #             headers = {"Authorization": f"Bearer {authed_session.credentials.token}"}
            
# #             async with client.stream("GET", url, headers=headers, timeout=60.0) as response:
# #                 response.raise_for_status()
# #                 async for chunk in response.aiter_bytes():
# #                     yield chunk
        
# #         print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Finished streaming file {gdrive_id}")

# #     except httpx.HTTPStatusError as e:
# #         print(f"!!! [{account.id}] Google API HTTP error during stream: {e.response.text}")
# #         raise e
# #     except Exception as e:
# #         print(f"!!! [{account.id}] Unexpected error during Google Drive stream: {e}")
# #         raise e



# # In file: Backend/app/services/google_drive_service.py

# import asyncio
# import httpx
# import json
# import time
# from typing import AsyncGenerator, List, Dict, Optional
# from collections import defaultdict
# import threading

# # Add Request for the token refresh mechanism
# from google.auth.transport.requests import AuthorizedSession, Request
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError

# from app.core.config import settings, GoogleAccountConfig

# SCOPES = ['https://www.googleapis.com/auth/drive']
# REQUEST_LIMIT_PER_MINUTE = 500
# DAILY_UPLOAD_LIMIT_BYTES = 740 * 1024 * 1024 * 1024

# class ApiUsageTracker:
#     # This class remains unchanged
#     def __init__(self):
#         self._lock = threading.Lock()
#         self.requests = defaultdict(lambda: {"minute_timestamp": 0, "count": 0})
#         self.uploads = defaultdict(lambda: {"day_timestamp": 0, "bytes": 0})

#     def increment_request_count(self, account_id: str):
#         # ...
#         with self._lock:
#             current_minute = int(time.time() / 60)
#             if self.requests[account_id]["minute_timestamp"] != current_minute:
#                 self.requests[account_id]["minute_timestamp"] = current_minute
#                 self.requests[account_id]["count"] = 0
#             self.requests[account_id]["count"] += 1

#     def increment_upload_volume(self, account_id: str, file_size_bytes: int):
#         # ...
#         with self._lock:
#             current_day = int(time.time() / 86400)
#             if self.uploads[account_id]["day_timestamp"] != current_day:
#                 self.uploads[account_id]["day_timestamp"] = current_day
#                 self.uploads[account_id]["bytes"] = 0
#             self.uploads[account_id]["bytes"] += file_size_bytes

#     def get_usage(self, account_id: str) -> dict:
#         # ...
#         with self._lock:
#             current_minute = int(time.time() / 60)
#             current_day = int(time.time() / 86400)
#             req_count = self.requests[account_id]["count"] if self.requests[account_id]["minute_timestamp"] == current_minute else 0
#             upload_bytes = self.uploads[account_id]["bytes"] if self.uploads[account_id]["day_timestamp"] == current_day else 0
#             return {"requests_this_minute": req_count, "bytes_today": upload_bytes}

# class GoogleDrivePoolManager:
#     # This class remains unchanged
#     _instance = None
#     _lock = threading.Lock()
#     def __new__(cls, *args, **kwargs):
#         if not cls._instance:
#             with cls._lock:
#                 if not cls._instance:
#                     cls._instance = super(GoogleDrivePoolManager, cls).__new__(cls)
#         return cls._instance
#     def __init__(self, accounts: List[GoogleAccountConfig]):
#         if not hasattr(self, '_initialized'):
#             self.accounts = accounts
#             self.account_map: Dict[str, GoogleAccountConfig] = {acc.id: acc for acc in accounts}
#             self.num_accounts = len(accounts)
#             self.current_account_index = 0
#             self.tracker = ApiUsageTracker()
#             self._async_lock = asyncio.Lock()
#             self._initialized = True
#             if self.num_accounts > 0:
#                 print(f"[GDRIVE_POOL] Initialized with {self.num_accounts} accounts. Active account: {self.get_current_account().id}")
#     def get_current_account(self) -> Optional[GoogleAccountConfig]:
#         if not self.accounts: return None
#         return self.accounts[self.current_account_index]
#     def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
#         return self.account_map.get(account_id)
#     async def get_active_account(self) -> Optional[GoogleAccountConfig]:
#         if self.num_accounts == 0: return None
#         async with self._async_lock:
#             for _ in range(self.num_accounts):
#                 account = self.get_current_account()
#                 usage = self.tracker.get_usage(account.id)
#                 if usage["requests_this_minute"] < REQUEST_LIMIT_PER_MINUTE and usage["bytes_today"] < DAILY_UPLOAD_LIMIT_BYTES:
#                     return account
#                 self.current_account_index = (self.current_account_index + 1) % self.num_accounts
#             return None

# gdrive_pool_manager = GoogleDrivePoolManager(settings.GDRIVE_ACCOUNTS)

# def _get_authed_session(account: GoogleAccountConfig) -> AuthorizedSession:
#     # This function remains unchanged
#     creds = Credentials.from_authorized_user_info(
#         info={"client_id": account.client_id, "client_secret": account.client_secret, "refresh_token": account.refresh_token},
#         scopes=SCOPES
#     )
#     return AuthorizedSession(creds)

# def create_resumable_upload_session(filename: str, filesize: int, account: GoogleAccountConfig) -> str:
#     # This function remains unchanged
#     try:
#         gdrive_pool_manager.tracker.increment_request_count(account.id)
#         metadata = {'name': filename, 'parents': [account.folder_id]}
#         headers = {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(filesize)}
#         authed_session = _get_authed_session(account)
#         init_response = authed_session.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable', headers=headers, data=json.dumps(metadata))
#         init_response.raise_for_status()
#         return init_response.headers['Location']
#     except Exception as e:
#         print(f"!!! [{account.id}] An unexpected error occurred in create_resumable_upload_session: {e}")
#         raise e

# # --- FINAL FIX: CORRECT TOKEN REFRESH LOGIC ---
# async def async_stream_gdrive_file(gdrive_id: str, account: GoogleAccountConfig) -> AsyncGenerator[bytes, None]:
#     """
#     Streams a file from Google Drive, correctly refreshing the token before
#     the download starts to support long-running transfers.
#     """
#     url = f"https://www.googleapis.com/drive/v3/files/{gdrive_id}?alt=media"
    
#     # Get a session object which holds the credentials
#     authed_session = _get_authed_session(account)
    
#     try:
#         gdrive_pool_manager.tracker.increment_request_count(account.id)
        
#         # --- THIS IS THE CORRECTED LOGIC ---
#         # 1. Check if the token is expired.
#         # 2. If it is, call refresh() on the CREDENTIALS object, not the session.
#         # 3. Run this blocking call in a thread to not freeze the server.
#         if authed_session.credentials.expired:
#             print(f"[GDRIVE_AUTH] Token for {account.id} is expired. Refreshing...")
#             # The refresh method is on the credentials object
#             await asyncio.to_thread(authed_session.credentials.refresh, Request())
#             print(f"[GDRIVE_AUTH] Token for {account.id} refreshed successfully.")
#         # --- END OF CORRECTED LOGIC ---

#         # Now that we know the token is valid, create the header
#         headers = {"Authorization": f"Bearer {authed_session.credentials.token}"}
            
#         async with httpx.AsyncClient() as client:
#             async with client.stream("GET", url, headers=headers, timeout=60.0) as response:
#                 response.raise_for_status()
#                 async for chunk in response.aiter_bytes():
#                     yield chunk
        
#         print(f"[ASYNC_GDRIVE_DOWNLOAD] [{account.id}] Finished streaming file {gdrive_id}")

#     except Exception as e:
#         print(f"!!! [{account.id}] Unexpected error during Google Drive stream: {e}")
#         raise e




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
    def get_current_account(self) -> Optional[GoogleAccountConfig]:
        if not self.accounts: return None
        return self.accounts[self.current_account_index]
    def get_account_by_id(self, account_id: str) -> Optional[GoogleAccountConfig]:
        return self.account_map.get(account_id)
    async def get_active_account(self) -> Optional[GoogleAccountConfig]:
        if self.num_accounts == 0: return None
        async with self._async_lock:
            for _ in range(self.num_accounts):
                account = self.get_current_account(); usage = self.tracker.get_usage(account.id)
                if usage["requests_this_minute"] < REQUEST_LIMIT_PER_MINUTE and usage["bytes_today"] < DAILY_UPLOAD_LIMIT_BYTES: return account
                self.current_account_index = (self.current_account_index + 1) % self.num_accounts
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
        metadata = {'name': filename, 'parents': [account.folder_id]}
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