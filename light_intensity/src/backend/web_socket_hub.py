import asyncio

from websockets import ServerConnection


class WebSocketHub:
    """Manages connected WebSocket clients and message broadcasting."""

    def __init__(self) -> None:
        self._connected_clients: set[ServerConnection] = set()

    async def handle_connection(self, websocket: ServerConnection) -> None:
        """Register and maintain a WebSocket client connection."""
        self._connected_clients.add(websocket)
        print(
            f"[WebSocket] Client connected. "
            f"Active clients: {len(self._connected_clients)}"
        )

        try:
            async for _ in websocket:
                pass
        finally:
            self._connected_clients.discard(websocket)
            print(
                f"[WebSocket] Client disconnected. "
                f"Active clients: {len(self._connected_clients)}"
            )

    async def broadcast(self, message: str) -> None:
        """Broadcast a message to all currently connected clients."""
        if not self._connected_clients:
            return

        connected_clients = tuple(self._connected_clients)

        print(
            f"[WebSocket] Broadcasting message to "
            f"{len(connected_clients)} client(s)"
        )

        await asyncio.gather(
            *(client.send(message) for client in connected_clients),
            return_exceptions=True,
        )
