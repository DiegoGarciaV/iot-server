# Arquitectura del backend — Smart Locker

Este documento resume las decisiones de diseño del backend. Distingue lo que ya está implementado de lo que está planeado.

## Resumen

El backend es **un solo servicio** (un contenedor, un proceso): una app de **FastAPI** que, al arrancar, también levanta el **cliente MQTT**. Se arranca con **uvicorn con un solo worker**.

La separación entre REST y MQTT se hace **por capas dentro del código**, no por contenedores. REST, MQTT y WebSocket son puntos de entrada delgados que traducen su protocolo y delegan en una **capa de servicios** común, donde vive toda la lógica de negocio.

```
            ESP32                         Frontend
              │ MQTT                    REST │  │ WebSocket
              ▼                              ▼  ▼
┌─────────────────────────────────────────────────────────┐
│  backend (FastAPI, 1 proceso)                           │
│                                                         │
│  Entradas (delgadas: parsean, validan y delegan)        │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ mqtt handler │   │ REST routers │   │ WS hub      │  │
│  └──────┬───────┘   └──────┬───────┘   └──────▲──────┘  │
│         └─────────┬────────┘                  │         │
│                   ▼                           │         │
│  Servicios (lógica de negocio) ───────────────┘         │
│         │                 │                             │
│         ▼                 ▼                             │
│  adapters (DB)      publisher MQTT (acciones al ESP32)  │
└─────────┬───────────────────────────────────────────────┘
          ▼
        MySQL
```

## Decisión: un solo servicio en lugar de dos contenedores

**Alternativa descartada:** un contenedor con la API REST, dueño de la lógica, y otro con el cliente MQTT, que llamaría a la API por HTTP.

Se descartó por estas razones:

- **El camino de regreso.** El backend también publica en MQTT (`session/action`). Las acciones que inicia el FE obligarían a que la API llamara al contenedor MQTT, o a tener dos clientes MQTT.
- **El WebSocket hub** debe vivir donde se conocen los eventos y el estado, así que todo terminaría convergiendo en la API de todas formas.
- **El salto HTTP puede perder eventos.** Si la API está caída cuando llega un evento, el PUBACK de QoS 1 ya se envió al broker y el evento se pierde, salvo que se implementen reintentos e idempotencia.
- **Más piezas sin beneficio.** No hay necesidad de escalar las partes por separado, desplegarlas de forma independiente ni de equipos distintos.

**Cuándo reconsiderarlo:** si se necesita más de un proceso. En ese caso se saca el handler MQTT a su propio contenedor, y la capa `services/` es la frontera natural para hacerlo.

## Capas y regla de dependencias

```
mqtt/handlers.py ──import──▶ services/ ◀──import── api/routers.py
                                 │
                                 ▼
                             adapters/ ──▶ db/
```

| Capa | Responsabilidad | Conoce MQTT/HTTP |
|---|---|---|
| `main.py` | *Composition root*: crea y conecta todas las piezas; arranca y detiene MQTT en el `lifespan` | Sí |
| `api/` | Routers REST y endpoint WebSocket. Traducen HTTP a llamadas a servicios | HTTP |
| `mqtt/` | `MQTTManager`, despachador de tópicos, handlers y publisher. Traducen MQTT a llamadas a servicios y servicios a MQTT | MQTT |
| `services/` | Lógica de negocio | **No** |
| `adapters/` | Acceso a datos por entidad, genérico sobre modelos de pydantic | No |
| `db/` | Conector de MySQL | No |
| `models/` | Modelos de pydantic y configuración | No |

**Regla:** `services/` nunca importa de `mqtt/` ni de `api/`. Si en un servicio aparece `import paho`, un tópico o un `Request` de FastAPI, algo está en la capa equivocada.

### Servicios como clases con dependencias inyectadas

Los servicios son clases que reciben sus dependencias (adapters, publisher, WS hub) en `__init__`. `main.py` las construye. Es el mismo patrón que `LockerAdapter(connector)` y permite usar dependencias falsas en los tests.

## Flujos

Hay dos flujos en el mismo proceso, y **ambos pasan por `services/`**. Un evento del ESP32 nunca se reenvía directo de MQTT a WebSocket: primero el servicio actualiza el estado en la DB y decide qué notificar al FE.

### Flujo 1 — Tiempo real (lo inicia el ESP32)

```
ESP32 → MQTT → dispatch → handler → service → DB (actualiza estado)
                                           └→ WS hub → FE (notifica)
```

### Flujo 2 — Peticiones (las inicia el FE)

```
FE → REST → router → service → DB (consulta o guarda)
                            └→ publisher → MQTT → ESP32 (si hay que actuar)
              ← respuesta HTTP
```

### Ciclo completo de una acción del FE

El publish es "dispara y olvida": que `publish` regrese `True` solo significa que el mensaje se encoló.

1. El FE hace `POST /sessions`. El servicio valida, guarda y publica `open_locker`.
2. El endpoint responde **`202 Accepted`** con estado `pending`, no "locker abierto".
3. El ESP32 abre el locker y publica el evento correspondiente.
4. Ese evento entra por el flujo 1: el servicio actualiza la DB y notifica al FE por WebSocket.

## Piezas clave

### Despachador MQTT

`MQTTManager` recibe un solo `message_handler`. El despachador relaciona cada patrón de tópico con su handler usando `mqtt.topic_matches_sub`, que entiende los wildcards `+` y `#`:

```python
ROUTES = {
    "smart-locker/locker/+/event": on_locker_event,
    "smart-locker/session/event": on_session_event,
    "smart-locker/session/event/locker/+": on_session_locker_event,
}

async def dispatch(topic: str, payload: str) -> None:
    for pattern, handler in ROUTES.items():
        if mqtt.topic_matches_sub(pattern, topic):
            return await handler(topic, payload)
    print(f"[MQTT] No handler for '{topic}'")
```

### Handlers MQTT

Equivalen a un router REST: parsean el tópico, validan el payload con pydantic y llaman al servicio.

```python
async def on_locker_event(topic: str, payload: str) -> None:
    locker_id = int(topic.split("/")[2])                 # smart-locker/locker/3/event
    event = LockerEvent.model_validate_json(payload)
    await locker_service.handle_event(locker_id, event)
```

### Publisher MQTT

Vive en `mqtt/` y expone métodos de dominio. Los tópicos y los formatos de payload quedan encapsulados aquí, así que el servicio solo ve `open_locker(locker_id)`.

```python
class LockerCommandPublisher:

    def __init__(self, mqtt_manager: MQTTManager) -> None:
        self.mqtt_manager = mqtt_manager

    def open_locker(self, locker_id: int) -> bool:
        return self.mqtt_manager.publish(
            topic=f"smart-locker/session/action/locker/{locker_id}",
            payload=json.dumps({"action": "open"}),
        )
```

`MQTTManager.publish` no bloquea (paho encola el mensaje y lo envía su hilo de red), así que se puede llamar desde endpoints async.

Opcional, para una separación más estricta: definir en `services/` un `Protocol` con `open_locker` y tipar el parámetro del servicio con él.

### `main.py` y `lifespan`

El `MQTTManager` necesita el event loop de uvicorn, que solo existe dentro del `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_manager = MQTTManager(config, dispatch, asyncio.get_running_loop())
    publisher = LockerCommandPublisher(mqtt_manager)
    session_service = SessionService(locker_adapter, publisher)
    mqtt_manager.start()
    yield
    mqtt_manager.stop()

app = FastAPI(lifespan=lifespan)
app.include_router(lockers_router)
```

### WebSocket hub

Se conserva la lógica actual de `WebSocketHub`: autenticar con el primer mensaje (el token), agrupar clientes por sesión, `send_to` y `disconnect`. Se servirá como **endpoint WebSocket de FastAPI**, en el mismo puerto que el REST, en lugar de un servidor aparte con la librería `websockets`. Hay que cambiar `ServerConnection` por el `WebSocket` de Starlette, y `broadcast` por un envío a cada cliente.

## Ejecución

```
uvicorn smart_locker.main:app --host 0.0.0.0 --port 8000
```

- **Un solo worker, siempre.** Con `--workers N`, cada proceso tendría su propio `MQTTManager` y su propio WS hub: los eventos se procesarían N veces y los clientes WebSocket quedarían repartidos entre procesos.
- En desarrollo se puede usar `--reload`. Cada recarga reconecta MQTT, y `MQTTManager` ya lo maneja (usa `connect_async` y se vuelve a suscribir en `_on_connect`).

## Estructura del proyecto

```
backend/
├── pyproject.toml          # paquete instalable (hatchling, uv package = true)
├── uv.lock
├── smart_locker/
│   ├── main.py             # (planeado) FastAPI app + lifespan
│   ├── api/                # (planeado) routers REST + endpoint WS
│   ├── mqtt/               # (planeado) manager, dispatch, handlers, publisher
│   ├── services/           # (planeado) lógica de negocio
│   ├── adapters/           # acceso a datos genérico
│   ├── db/                 # conector MySQL y excepciones
│   ├── models/             # modelos pydantic y configuración
│   ├── exceptions.py       # excepciones de dominio
│   ├── mqtt_manager.py     # se moverá a mqtt/
│   └── web_socket_hub.py   # se adaptará a FastAPI y se moverá a api/
└── tests/                  # fuera del paquete
```

## Convenciones

- **Imports absolutos desde el paquete:** `from smart_locker.adapters.base_adapter import ...`. El paquete se instala en modo editable con `uv sync`, así que los imports funcionan desde cualquier directorio.
- **Usar `python`, no `python3`, en Windows.** El venv solo trae `python.exe`; `python3` apunta al Python global de la Microsoft Store. También se puede usar `uv run python ...`.
- **Tablas de MySQL en singular** (`locker`), igual que las entidades (`LockerModel`, `LockerAdapter`).
- **Adapters genéricos:** cada adapter declara su modelo y su tabla.

  ```python
  class LockerAdapter(SmartLockerAdapter[LockerModel]):
      model = LockerModel
      table_name = "locker"
  ```

  Los valores siempre van como parámetros (`%s` o `%(name)s`), nunca interpolados en el SQL.

## Esquema actual

```sql
CREATE TABLE IF NOT EXISTS locker (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    status ENUM(
        'available', 'reserved', 'depositing',
        'occupied', 'picking_up', 'unavailable'
    ) NOT NULL DEFAULT 'available',
    PRIMARY KEY (id)
);
```

Los valores del `ENUM` deben coincidir con `LockerStatus`.

## Pendientes

- [ ] Crear `main.py` con FastAPI y el `lifespan`.
- [ ] Mover `mqtt_manager.py` a `mqtt/` y agregar el despachador, los handlers y el publisher.
- [ ] Crear la capa `services/` (`LockerService`, `SessionService`).
- [ ] Adaptar `WebSocketHub` a FastAPI y exponerlo como endpoint.
- [ ] Definir los endpoints del FE (mínimo: disponibilidad de lockers, crear o reservar sesión, token para el WS, cancelar).
- [ ] Definir los modelos de los payloads MQTT (por ejemplo, `LockerEvent`).
- [ ] Extender `DBConnector` para escrituras (`commit`) y agregar `create`, `update` y `delete` al adapter base.
- [ ] Alinear el tipo de `params` en `DBConnector.run_query` (hoy es `Dict`) con `get_by_key`, que pasa una tupla.
- [ ] Migrar los scripts de `tests/` a pytest con fixtures en `conftest.py`.
- [ ] Dockerfile del backend y servicio en `docker-compose.yml`.
