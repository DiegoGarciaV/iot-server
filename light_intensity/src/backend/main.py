"""MQTT to WebSocket bridge.

Subscribes to MQTT messages published by IoT devices and broadcasts
the received payloads to all connected WebSocket clients.
"""

import asyncio
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from websockets.asyncio.server import ServerConnection, serve


@dataclass(frozen=True)
class ApplicationConfig:
    """Application connection settings."""

    mqtt_broker_host: str = "mqtt_broker"
    mqtt_broker_port: int = 1883
    mqtt_topic: str = "prueba/tema"

    websocket_host: str = "0.0.0.0"
    websocket_port: int = 81


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


class MQTTSubscriber:
    """Subscribes to MQTT messages and forwards them to the WebSocket layer."""

    def __init__(
        self,
        config: ApplicationConfig,
        websocket_hub: WebSocketHub,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._config = config
        self._websocket_hub = websocket_hub
        self._event_loop = event_loop

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self._client.on_message = self._on_message

    def start(self) -> None:
        """Connect to the MQTT broker and start the network loop."""
        self._client.connect(
            host=self._config.mqtt_broker_host,
            port=self._config.mqtt_broker_port,
            keepalive=60,
        )
        self._client.subscribe(self._config.mqtt_topic)
        self._client.loop_start()

        print(
            f"[MQTT] Listening on topic "
            f"'{self._config.mqtt_topic}' at "
            f"{self._config.mqtt_broker_host}:"
            f"{self._config.mqtt_broker_port}"
        )

    def stop(self) -> None:
        """Stop the MQTT network loop and disconnect from the broker."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        """Handle an incoming MQTT message."""
        payload = message.payload.decode("utf-8")

        print(
            f"[MQTT] Message received from '{message.topic}': "
            f"{payload}"
        )

        asyncio.run_coroutine_threadsafe(
            self._websocket_hub.broadcast(payload),
            self._event_loop,
        )


class Application:
    """Coordinates MQTT ingestion and WebSocket communication."""

    def __init__(self, config: ApplicationConfig) -> None:
        self._config = config
        self._websocket_hub = WebSocketHub()
        self._mqtt_subscriber: MQTTSubscriber | None = None

    async def run(self) -> None:
        """Start all application services."""
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
                    f"[WebSocket] Server listening on "
                    f"{self._config.websocket_host}:"
                    f"{self._config.websocket_port}"
                )

                await asyncio.Future()
        finally:
            self._mqtt_subscriber.stop()


async def main() -> None:
    """Application entry point."""
    config = ApplicationConfig()
    application = Application(config)

    await application.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication stopped.")