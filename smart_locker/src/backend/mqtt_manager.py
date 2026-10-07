import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future

import paho.mqtt.client as mqtt

from models import ApplicationConfig


MessageHandler = Callable[[str, str], Awaitable[None]]


class MQTTManager:
    """Manages the MQTT connection: subscribes to topics and publishes messages."""

    def __init__(
        self,
        config: ApplicationConfig,
        message_handler: MessageHandler,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._config = config
        self._message_handler = message_handler
        self._event_loop = event_loop

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message

        self._client.tls_set(
            ca_certs=self._config.mqtt_ca_certificate,
            certfile=self._config.mqtt_client_certificate,
            keyfile=self._config.mqtt_client_private_key,
        )

    def start(self) -> None:
        """Connect to the MQTT broker and start the network loop.

        Uses connect_async so the network thread retries with backoff
        instead of raising if the broker isn't accepting connections yet.
        """
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
        """Disconnect from the broker and stop the MQTT network loop.

        Disconnects first so the network thread can still send the
        DISCONNECT packet before it is stopped.
        """
        self._client.disconnect()
        self._client.loop_stop()

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int | None = None,
        retain: bool = False,
    ) -> bool:
        """Publish a message to the given topic.

        Thread-safe and non-blocking: the message is queued and sent by the
        network thread. Returns False if the client rejected the message
        (e.g. QoS 0 while disconnected); QoS 1/2 messages published while
        disconnected are kept and sent on reconnect.
        """
        qos = self._config.mqtt_qos if qos is None else qos

        message_info = self._client.publish(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain,
        )

        if message_info.rc == mqtt.MQTT_ERR_NO_CONN and qos > 0:
            print(
                f"[MQTT] Not connected. Message to '{topic}' queued "
                f"until reconnect: {payload}"
            )
            return True

        if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(
                f"[MQTT] Publish to '{topic}' failed: "
                f"{mqtt.error_string(message_info.rc)}"
            )
            return False

        print(f"[MQTT] Message published to '{topic}': {payload}")
        return True

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """Subscribe to the configured topics on every (re)connect."""
        if reason_code.is_failure:
            print(f"[MQTT] Connection failed: {reason_code}")
            return

        topics = self._config.mqtt_subscribe_topics
        print(f"[MQTT] Connected. Subscribing to {list(topics)}")

        if topics:
            client.subscribe(
                [(topic, self._config.mqtt_qos) for topic in topics]
            )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """Log disconnections; the network loop reconnects on its own."""
        print(f"[MQTT] Disconnected: {reason_code}")

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata: object,
        mid: int,
        reason_code_list: list[mqtt.ReasonCode],
        properties: mqtt.Properties | None,
    ) -> None:
        """Report subscriptions rejected by the broker (e.g. by the ACL)."""
        topics = self._config.mqtt_subscribe_topics

        for topic, reason_code in zip(topics, reason_code_list):
            if reason_code.is_failure:
                print(f"[MQTT] Subscription to '{topic}' failed: {reason_code}")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        """Hand an incoming MQTT message over to the event loop."""
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            print(
                f"[MQTT] Discarded non UTF-8 message from '{message.topic}'"
            )
            return

        print(
            f"[MQTT] Message received from '{message.topic}': "
            f"{payload}"
        )

        future = asyncio.run_coroutine_threadsafe(
            self._message_handler(message.topic, payload),
            self._event_loop,
        )
        future.add_done_callback(self._log_handler_error)

    @staticmethod
    def _log_handler_error(future: Future[None]) -> None:
        """Surface exceptions raised by the message handler."""
        if future.cancelled():
            return

        error = future.exception()
        if error is not None:
            print(f"[MQTT] Message handler failed: {error!r}")
