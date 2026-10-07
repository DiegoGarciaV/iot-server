from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationConfig:
    """Application connection settings."""

    mqtt_broker_host: str = "mqtt_broker"
    mqtt_broker_port: int = 8883
    mqtt_subscribe_topics: tuple[str, ...] = (
        "smart-locker/session/event",
        "smart-locker/session/event/locker/+",
        "smart-locker/locker/+/event",
    )
    mqtt_qos: int = 1
    mqtt_ca_certificate: str = "/app/certs/ca.crt"
    mqtt_client_certificate: str = "/app/certs/backend.crt"
    mqtt_client_private_key: str = "/app/certs/backend.key"

    websocket_host: str = "0.0.0.0"
    websocket_port: int = 81
