
import asyncio


import paho.mqtt.client as mqtt

from models import ApplicationConfig
from web_socket_hub import WebSocketHub


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
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self) -> None:
        """Connect to the MQTT broker and start the network loop.

        Uses connect_async so the network thread retries with backoff
        instead of raising if the broker isn't accepting connections yet.
        """

        self._client.tls_set(
            ca_certs=self._config.mqtt_ca_certificate,
            certfile=self._config.mqtt_client_certificate,
            keyfile=self._config.mqtt_client_private_key,
        )

        self._client.connect_async(
            host=self._config.mqtt_broker_host,
            port=self._config.mqtt_broker_port,
            keepalive=60,
        )
        self._client.loop_start()

        print(
            f"[MQTT] Connecting to "
            f"{self._config.mqtt_broker_host}:"
            f"{self._config.mqtt_broker_port}"
        )

    def stop(self) -> None:
        """Stop the MQTT network loop and disconnect from the broker."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """Subscribe to the configured topic on every (re)connect."""
        if reason_code.is_failure:
            print(f"[MQTT] Connection failed: {reason_code}")
            return

        client.subscribe(self._config.mqtt_topic)
        print(f"[MQTT] Connected. Subscribed to '{self._config.mqtt_topic}'")

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

