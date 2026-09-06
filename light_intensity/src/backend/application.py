"""MQTT to WebSocket application service.

Coordinates MQTT ingestion and WebSocket communication.
"""

import asyncio

from websockets.asyncio.server import serve

from models import ApplicationConfig
from mqtt_subscriber import MQTTSubscriber
from web_socket_hub import WebSocketHub


class Application:
    """Coordinates MQTT ingestion and WebSocket communication."""

    def __init__(self, config: ApplicationConfig) -> None:
        self._config = config
        self._websocket_hub = WebSocketHub()
        self._mqtt_subscriber: MQTTSubscriber | None = None

    async def run(self) -> None:
        """Start the MQTT subscriber and WebSocket server."""
        event_loop = asyncio.get_running_loop()

        self._mqtt_subscriber = MQTTSubscriber(
            config=self._config,
            websocket_hub=self._websocket_hub,
            event_loop=event_loop,
        )

        self._mqtt_subscriber.start()

        try:
            async with serve(
                self._websocket_hub.handle_connection,
                self._config.websocket_host,
                self._config.websocket_port,
            ):
                print(
                    "[WebSocket] Server listening on "
                    f"{self._config.websocket_host}:"
                    f"{self._config.websocket_port}"
                )

                await asyncio.Future()
        finally:
            self._mqtt_subscriber.stop()