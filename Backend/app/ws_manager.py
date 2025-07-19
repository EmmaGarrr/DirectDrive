# FILE: Backend/app/ws_manager.py

from fastapi import WebSocket
from typing import List

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print("Admin client connected.")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print("Admin client disconnected.")

    async def broadcast(self, data: dict):
        for connection in self.active_connections:
            await connection.send_json(data)

# Create the single, global instance that the rest of our app will import and use
manager = ConnectionManager()
