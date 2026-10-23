import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

from smart_locker.models.config_model import ApplicationConfig


MessageHandler = Callable[[str, str], None]


class MQTTManager:
    """Manages the MQTT connection: subscribes to topics and publishes messages.

    Runs in the caller's thread: the owner calls loop() repeatedly, and every
    message received is handed to the message handler from inside loop().
    """

    def __init__(
        self,
        config: ApplicationConfig,
        message_handler: MessageHandler,
    ) -> None:
        self._config = config
        self._message_handler = message_handler
        self._running = False
        self._last_connect_attempt = 0.0

        # A fixed client id with clean_session=False makes the broker keep
        # the subscriptions and queue QoS 1 messages while we are offline.
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._config.mqtt_client_id,
            clean_session=False,
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
        """Set the broker to connect to.

        The connection itself is made by loop(), so a broker that isn't
        accepting connections yet is retried instead of raising here.
        """
        self._client.connect_async(
            host=self._config.mqtt_broker_host,
            port=self._config.mqtt_broker_port,
            keepalive=60,
        )
        self._running = True

        print(
            f"[MQTT] Connecting to "
            f"{self._config.mqtt_broker_host}:"
            f"{self._config.mqtt_broker_port}"
        )

    def loop(self, timeout: float = 1.0) -> None:
        """Process network traffic for up to `timeout` seconds.

        Must be called repeatedly. Received messages are handed to the
        message handler from here. While disconnected, it reconnects at most
        once every `mqtt_reconnect_delay` seconds and otherwise just waits.
        """
        if self._client.socket() is None:
            if not (self._running and self._reconnect()):
                time.sleep(timeout)
                return

        self._client.loop(timeout=timeout)

    def stop(self) -> None:
        """Disconnect from the broker; loop() won't reconnect afterwards."""
        self._running = False
        self._client.disconnect()

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int | None = None,
        retain: bool = False,
    ) -> bool:
        """Publish a message to the given topic.

        Non-blocking: the message is queued and sent from loop(). Returns
        False if the client rejected the message (e.g. QoS 0 while
        disconnected); QoS 1/2 messages published while disconnected are
        kept and sent on reconnect.
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

    def _reconnect(self) -> bool:
        """Open a new connection if the retry delay has passed.

        Returns True if the socket was opened; the broker's answer arrives
        later through _on_connect.
        """
        now = time.monotonic()
        if now - self._last_connect_attempt < self._config.mqtt_reconnect_delay:
            return False

        self._last_connect_attempt = now
        try:
            self._client.reconnect()
        except OSError as error:
            print(f"[MQTT] Connection attempt failed: {error!r}")
            return False

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
        """Log disconnections; loop() reconnects on its own."""
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
        """Hand an incoming MQTT message over to the message handler."""
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

        # paho re-raises callback errors out of loop(), so a single bad
        # message would otherwise stop the caller's loop.
        try:
            self._message_handler(message.topic, payload)
        except Exception as error:
            print(f"[MQTT] Message handler failed: {error!r}")
