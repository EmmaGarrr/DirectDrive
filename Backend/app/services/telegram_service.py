# In file: Backend/app/services/telegram_service.py

import httpx
from app.core.config import settings
from typing import AsyncGenerator, List

# Define the base API URL for the Telegram bot
TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
# Define a safe chunk size, slightly less than the 20MB technical limit.
TELEGRAM_CHUNK_SIZE_BYTES = 18 * 1024 * 1024

def upload_chunk_and_get_file_id(chunk_data: bytes, filename: str) -> str:
    """
    Uploads a single binary chunk as a document and returns its file_id.
    This is synchronous and designed to be called from a Celery task.
    """
    # --- THIS IS THE DEFINITIVE, COMPATIBLE FIX ---
    # This sets ALL timeout values (connect, read, write, pool) to 300 seconds (5 minutes).
    # This syntax is compatible with older versions of httpx and solves the WriteTimeout.
    timeout_config = httpx.Timeout(300.0)

    with httpx.Client(timeout=timeout_config) as client:
        url = f"{TELEGRAM_API_URL}/sendDocument"
        params = {'chat_id': settings.TELEGRAM_CHANNEL_ID}
        files = {'document': (filename, chunk_data, 'application/octet-stream')}
        
        try:
            print(f"[TELEGRAM_SERVICE] Uploading chunk '{filename}' to get file_id...")
            response = client.post(url, params=params, files=files)
            response.raise_for_status()
            
            data = response.json()
            if data.get('ok'):
                file_id = data['result']['document']['file_id']
                print(f"[TELEGRAM_SERVICE] Chunk uploaded successfully. File ID: {file_id}")
                return file_id
            else:
                raise Exception(f"Telegram API Error: {data.get('description', 'Unknown error')}")

        except httpx.RequestError as e:
            print(f"!!! [TELEGRAM_SERVICE] HTTP request failed: {e}")
            raise

# --- ASYNC FUNCTIONS FOR STREAMING DOWNLOAD ---

async def get_file_path(file_id: str, client: httpx.AsyncClient) -> str:
    """Gets the internal file_path from a file_id using an existing client session."""
    url = f"{TELEGRAM_API_URL}/getFile"
    params = {'file_id': file_id}
    response = await client.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    if data.get("ok"):
        return data['result']['file_path']
    else:
        raise Exception(f"Telegram getFile Error: {data.get('description')}")

async def stream_file_from_telegram(file_ids: List[str]) -> AsyncGenerator[bytes, None]:
    """
    Accepts a list of Telegram file_ids, fetches each one, and streams its content.
    This is asynchronous and designed for FastAPI route handlers.
    """
    print(f"[TELEGRAM_SERVICE] Streaming {len(file_ids)} chunks from Telegram.")
    
    timeout_config = httpx.Timeout(60.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        for file_id in file_ids:
            try:
                file_path = await get_file_path(file_id, client)
                download_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
                
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
                print(f"[TELEGRAM_SERVICE] Finished streaming chunk with file_id: {file_id}")
            except Exception as e:
                print(f"!!! [TELEGRAM_SERVICE] Failed to stream chunk {file_id}: {e}")
                break