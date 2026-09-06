

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationConfig:
    """Application connection settings."""

    mqtt_broker_host: str = "mqtt_broker"
    mqtt_broker_port: int = 8883
    mqtt_topic: str = "prueba/tema"
    mqtt_ca_certificate: str = "/app/certs/ca.crt"

    websocket_host: str = "0.0.0.0"
    websocket_port: int = 81
