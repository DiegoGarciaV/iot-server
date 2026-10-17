import asyncio
from collections.abc import Awaitable, Callable

from websockets.asyncio.server import ServerConnection, broadcast
from websockets.exceptions import ConnectionClosed


Authenticator = Callable[[str], Awaitable[str | None]]
MessageHandler = Callable[[str, str], Awaitable[None]]

POLICY_VIOLATION = 1008


class WebSocketHub:
    """Manages authenticated WebSocket clients and message exchange with them.

    Every client must send its access token as the first message. The
    authenticator resolves the token to a session id (or None to reject it);
    from then on the client only receives messages sent to that session.
    """

    def __init__(
        self,
        authenticator: Authenticator,
        message_handler: MessageHandler,
        authentication_timeout: float = 10.0,
    ) -> None:
        self._authenticator = authenticator
        self._message_handler = message_handler
        self._authentication_timeout = authentication_timeout
        self._clients_by_session: dict[str, set[ServerConnection]] = {}

    async def handle_connection(self, websocket: ServerConnection) -> None:
        """Authenticate a WebSocket client and process the messages it sends."""
        session_id = await self._authenticate(websocket)

        if session_id is None:
            print("[WebSocket] Client rejected: authentication failed")
            await websocket.close(POLICY_VIOLATION, "Unauthorized")
            return

        clients = self._clients_by_session.setdefault(session_id, set())
        clients.add(websocket)
        print(
            f"[WebSocket] Client connected to session '{session_id}'. "
            f"Active clients: {len(clients)}"
        )

        try:
            async for message in websocket:
                await self._handle_message(session_id, message)
        except ConnectionClosed:
            pass
        finally:
            clients.discard(websocket)
            if not clients:
                self._clients_by_session.pop(session_id, None)
            print(
                f"[WebSocket] Client disconnected from session "
                f"'{session_id}'. Active clients: {len(clients)}"
            )

    async def send_to(self, session_id: str, message: str) -> None:
        """Send a message to every client connected to the given session."""
        clients = self._clients_by_session.get(session_id)
        if not clients:
            return

        print(
            f"[WebSocket] Sending message to session '{session_id}' "
            f"({len(clients)} client(s))"
        )

        broadcast(clients, message)

    async def disconnect(self, session_id: str) -> None:
        """Close every client of a session, e.g. once its token expires."""
        clients = tuple(self._clients_by_session.get(session_id, ()))

        await asyncio.gather(
            *(client.close(POLICY_VIOLATION, "Session ended") for client in clients),
            return_exceptions=True,
        )

    async def _authenticate(self, websocket: ServerConnection) -> str | None:
        """Resolve the client's first message (its token) to a session id."""
        try:
            async with asyncio.timeout(self._authentication_timeout):
                token = await websocket.recv()
        except (TimeoutError, ConnectionClosed):
            return None

        if not isinstance(token, str):
            return None

        try:
            return await self._authenticator(token)
        except Exception as error:
            print(f"[WebSocket] Authenticator failed: {error!r}")
            return None

    async def _handle_message(
        self,
        session_id: str,
        message: str | bytes,
    ) -> None:
        """Forward a client message to the handler along with its session."""
        if not isinstance(message, str):
            print(f"[WebSocket] Discarded binary message from '{session_id}'")
            return

        print(f"[WebSocket] Message received from '{session_id}': {message}")

        try:
            await self._message_handler(session_id, message)
        except Exception as error:
            print(f"[WebSocket] Message handler failed: {error!r}")
