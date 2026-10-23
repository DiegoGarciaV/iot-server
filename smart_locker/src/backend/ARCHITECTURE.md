# Arquitectura del backend — Smart Locker

Este documento resume las decisiones de diseño del backend. Distingue lo que ya está implementado de lo que está planeado. Lo que el backend debe hacer está en [USE_CASES.md](USE_CASES.md).

## Resumen

El backend es **un solo servicio** (un contenedor, un proceso): una app de **FastAPI** que, al arrancar, también levanta el **cliente MQTT**. Se arranca con **uvicorn con un solo worker**.

La separación entre REST y MQTT se hace **por capas dentro del código**, no por contenedores. REST, MQTT y WebSocket son puntos de entrada delgados que traducen su protocolo y delegan en una **capa de servicios** común, donde vive toda la lógica de negocio.

El "Frontend" de este documento es el **FE web** (reservar, consultar pedido, generar tokens). El FE local que sirve el ESP32 frente al locker habla solo con el ESP32; al backend le llega por MQTT.

```
            ESP32                      FE web
              │ MQTT                 REST │  │ WebSocket
              ▼                           ▼  ▼
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

- **El camino de regreso.** Validar un `TOKEN_ENTERED` termina publicando `START_*` o `ACCESS_DENIED`. Con dos contenedores, cada evento haría un viaje de ida y vuelta por HTTP entre ellos, o ambos necesitarían cliente MQTT.
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
| `main.py` | *Composition root*: crea y conecta todas las piezas; arranca y detiene MQTT y las tareas periódicas en el `lifespan` | Sí |
| `api/` | Routers REST y endpoint WebSocket. Traducen HTTP a llamadas a servicios | HTTP |
| `mqtt/` | `MQTTManager`, despachador de tópicos, handlers y publisher. Traducen MQTT a llamadas a servicios y servicios a MQTT | MQTT |
| `services/` | Lógica de negocio | **No** |
| `adapters/` | Acceso a datos por entidad, genérico sobre modelos de pydantic | No |
| `db/` | Conector de MySQL | No |
| `models/` | Modelos de pydantic y configuración | No |

**Regla:** `services/` nunca importa de `mqtt/` ni de `api/`. Si en un servicio aparece `import paho`, un tópico o un `Request` de FastAPI, algo está en la capa equivocada.

### Servicios como clases con dependencias inyectadas

Los servicios son clases que reciben sus dependencias (adapters, publisher, WS hub) en `__init__`. `main.py` las construye. Es el mismo patrón que `LockerAdapter(connector)` y permite usar dependencias falsas en los tests.

Se eligieron clases en lugar de funciones que reciben las dependencias como parámetros porque esas dependencias habría que pasarlas en cada llamada desde cada handler y router, y terminarían centralizándose de todas formas. La clase es esa centralización: las dependencias se inyectan una sola vez.

Reglas:

1. **Un servicio por responsabilidad del dominio**, no uno que lo haga todo. Si un servicio pasa de unas 4 dependencias, probablemente está haciendo demasiado.
2. **Todo se construye en `main.py`.** Ningún servicio crea sus propias dependencias.
3. **Sin ciclos entre servicios.** Si dos servicios se necesitan mutuamente, la lógica compartida va a un tercer componente o a una función pura.
4. **Lógica pura en funciones sueltas.** Transiciones de estado, validaciones y cálculos no necesitan `self` y se testean sin armar nada.
5. **Opcional:** tipar las dependencias externas (publisher, WS hub) con un `Protocol` definido en `services/`, para que `services/` no dependa ni indirectamente de `mqtt/` o `api/`.

### Servicios planeados

| Servicio | Casos de uso | Dependencias |
|---|---|---|
| `LockerService` | CU-1, CU-8 | `LockerAdapter` |
| `ReservationService` | CU-2, CU-3, CU-9, CU-10 | `LockerAdapter`, `ReservationAdapter`, `AccessTokenAdapter`, WS hub |
| `AccessService` | CU-4a, CU-4 | `LockerAdapter`, `AccessTokenAdapter`, publisher, WS hub |
| `OperationService` | CU-5, CU-6, CU-7, CU-11 | `LockerAdapter`, `ReservationAdapter`, WS hub |

## Flujos

Hay dos flujos en el mismo proceso, y **ambos pasan por `services/`**. Un evento del ESP32 nunca se reenvía directo de MQTT a WebSocket: primero el servicio actualiza el estado en la DB y decide qué publicar y qué notificar.

### Flujo 1 — Eventos del ESP32

```
ESP32 → MQTT → dispatch → handler → service → DB (actualiza estado)
                                           ├→ publisher → MQTT → ESP32 (solo en TOKEN_ENTERED)
                                           └→ WS hub → FE web (notifica)
```

### Flujo 2 — Peticiones del FE web

```
FE web → REST → router → service → DB (consulta o guarda)
                                └→ WS hub → FE web (si cambió una reserva)
                 ← respuesta HTTP
```

**REST nunca publica en MQTT.** Toda acción hacia el ESP32 es la respuesta a un `TOKEN_ENTERED`. El FE web no abre lockers: el usuario abre el locker frente a él, ingresando un token en el FE local del ESP32.

### Tareas periódicas

Algunos casos de uso no los dispara ninguna entrada: expirar reservas sin depósito (CU-10) y revertir operaciones colgadas (CU-11). Se implementan como una tarea `asyncio` que arranca en el `lifespan` y llama periódicamente al servicio correspondiente.

### Ciclo completo de un depósito

```
1. FE web   POST reserva                 → backend asigna locker: available → reserved
2. FE web   POST token de apertura       → backend crea AccessToken(DEPOSIT)
3. Usuario  ingresa el token en el FE local del ESP32
4. ESP32    session/event  TOKEN_ENTERED → backend valida, marca el token usado,
                                           reserved → depositing
5. backend  session/action/locker/{id}  START_DEPOSIT
6. ESP32    abre, detecta paquete, espera que cierre la puerta
7. ESP32    session/event/locker/{id}  DEPOSIT_COMPLETED
8. backend  depositing → occupied; notifica al FE web por WebSocket
```

La recogida es igual con un token `PICKUP`, `START_PICKUP` y `PICKUP_COMPLETED`, que termina en `available`. Los fallos están en [USE_CASES.md](USE_CASES.md#cu-7--operación-fallida).

El publish es "dispara y olvida": que `publish` regrese `True` solo significa que el mensaje se encoló. Como el protocolo no tiene ACK, si un `START_*` se pierde lo detecta CU-11.

## Piezas clave

### Despachador MQTT

`MQTTManager` recibe un solo `message_handler`. El despachador relaciona cada patrón de tópico con su handler usando `mqtt.topic_matches_sub`, que entiende los wildcards `+` y `#`:

```python
ROUTES = {
    "smart-locker/session/event": on_session_event,
    "smart-locker/session/event/locker/+": on_session_locker_event,
    "smart-locker/locker/+/event": on_locker_event,
}

async def dispatch(topic: str, payload: str) -> None:
    for pattern, handler in ROUTES.items():
        if mqtt.topic_matches_sub(pattern, topic):
            return await handler(topic, payload)
    print(f"[MQTT] No handler for '{topic}'")
```

### Handlers MQTT

Equivalen a un router REST: parsean el tópico, validan el payload con pydantic y llaman al servicio. Dentro de un tópico, el campo `type` del payload decide qué método del servicio se llama.

```python
async def on_session_locker_event(topic: str, payload: str) -> None:
    locker_id = int(topic.split("/")[-1])                # smart-locker/session/event/locker/3
    event = SessionLockerEvent.model_validate_json(payload)

    match event.type:
        case "DEPOSIT_COMPLETED":
            await operation_service.deposit_completed(locker_id, event.session_id)
        case "PICKUP_COMPLETED":
            await operation_service.pickup_completed(locker_id, event.session_id)
        case "OPERATION_FAILED":
            await operation_service.operation_failed(locker_id, event.session_id, event.reason)
```

Eventos por tópico (protocolo congelado del ESP32):

| Tópico | `type` | Payload |
|---|---|---|
| `smart-locker/session/event` | `TOKEN_ENTERED` | `type`, `sessionId`, `token` |
| `smart-locker/session/event/locker/{id}` | `DEPOSIT_COMPLETED`, `PICKUP_COMPLETED` | `type`, `sessionId` |
| `smart-locker/session/event/locker/{id}` | `OPERATION_FAILED` | `type`, `sessionId`, `reason` |
| `smart-locker/locker/{id}/event` | `LOCKER_RECOVERED` | `type` |

### Publisher MQTT

Vive en `mqtt/` y expone métodos de dominio. Los tópicos y los formatos de payload quedan encapsulados aquí, así que el servicio solo ve `start_deposit(locker_id, session_id)`.

```python
class LockerCommandPublisher:

    def __init__(self, mqtt_manager: MQTTManager) -> None:
        self.mqtt_manager = mqtt_manager

    def start_deposit(self, locker_id: int, session_id: str) -> bool:
        return self._publish_locker_action(locker_id, "START_DEPOSIT", session_id)

    def start_pickup(self, locker_id: int, session_id: str) -> bool:
        return self._publish_locker_action(locker_id, "START_PICKUP", session_id)

    def deny_access(self, session_id: str) -> bool:
        return self.mqtt_manager.publish(
            topic="smart-locker/session/action",
            payload=json.dumps({
                "type": "ACCESS_DENIED",
                "sessionId": session_id,
                "reason": "INVALID_CREDENTIALS",
            }),
        )

    def _publish_locker_action(self, locker_id: int, action: str, session_id: str) -> bool:
        return self.mqtt_manager.publish(
            topic=f"smart-locker/session/action/locker/{locker_id}",
            payload=json.dumps({"type": action, "sessionId": session_id}),
        )
```

`MQTTManager.publish` no bloquea (paho encola el mensaje y lo envía su hilo de red), así que se puede llamar desde código async.

### `MQTTManager`

Ya implementado. Se conecta con **mTLS**: `tls_set` recibe el CA y además el certificado y la llave del backend (`smart-locker-backend`). El broker exige certificado de cliente (`require_certificate true`) y usa su CN como usuario para el ACL (`use_identity_as_username true`).

### `main.py` y `lifespan`

El `MQTTManager` necesita el event loop de uvicorn, que solo existe dentro del `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_manager = MQTTManager(config, dispatch, asyncio.get_running_loop())
    publisher = LockerCommandPublisher(mqtt_manager)
    access_service = AccessService(locker_adapter, access_token_adapter, publisher, ws_hub)
    ...
    mqtt_manager.start()
    periodic = asyncio.create_task(run_periodic_tasks(reservation_service, operation_service))
    yield
    periodic.cancel()
    mqtt_manager.stop()

app = FastAPI(lifespan=lifespan)
app.include_router(reservations_router)
```

### WebSocket hub

Se conserva la lógica actual de `WebSocketHub`: autenticar con el primer mensaje, agrupar clientes, `send_to` y `disconnect`. Cambia esto:

- **Se agrupa por reserva, no por sesión.** El primer mensaje es el **código de reserva** y el `authenticator` lo resuelve a un `reservation_id`. Hay que renombrar `session_id` en el hub para no confundirlo con el `sessionId` del ESP32.
- Se servirá como **endpoint WebSocket de FastAPI**, en el mismo puerto que el REST, en lugar de un servidor aparte con la librería `websockets`. Hay que cambiar `ServerConnection` por el `WebSocket` de Starlette, y `broadcast` por un envío a cada cliente.
- Cuando una reserva termina, el servicio llama a `disconnect(reservation_id)`.

## Ejecución

```
uvicorn smart_locker.main:app --host 0.0.0.0 --port 8000
```

- **Un solo worker, siempre.** Con `--workers N`, cada proceso tendría su propio `MQTTManager`, su propio WS hub y sus propias tareas periódicas: los eventos se procesarían N veces y los clientes WebSocket quedarían repartidos entre procesos.
- En desarrollo se puede usar `--reload`. Cada recarga reconecta MQTT, y `MQTTManager` ya lo maneja (usa `connect_async` y se vuelve a suscribir en `_on_connect`).

## Estructura del proyecto

```
backend/
├── pyproject.toml          # paquete instalable (hatchling, uv package = true)
├── uv.lock
├── ARCHITECTURE.md
├── USE_CASES.md
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
- **"Sesión" es del ESP32.** En el backend, la entidad persistente es la reserva (`Reservation`). `sessionId` solo aparece en los payloads MQTT.
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

### Cambios planeados

```sql
ALTER TABLE locker
    ADD COLUMN status_since DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS reservation (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    code VARCHAR(32) NOT NULL,
    locker_id INT UNSIGNED NOT NULL,
    status ENUM('active', 'completed', 'cancelled', 'expired', 'failed')
        NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    closed_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY (code),
    FOREIGN KEY (locker_id) REFERENCES locker (id)
);

CREATE TABLE IF NOT EXISTS access_token (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    reservation_id INT UNSIGNED NOT NULL,
    token CHAR(8) NOT NULL,
    purpose ENUM('deposit', 'pickup') NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY (token),
    FOREIGN KEY (reservation_id) REFERENCES reservation (id)
);
```

`status_since` sirve para detectar operaciones colgadas (CU-11).

## Pendientes

- [ ] Agregar `fastapi`, `uvicorn` y `pytest` (dev) a `pyproject.toml`. Quitar `websockets` cuando el hub use FastAPI.
- [ ] Crear `main.py` con FastAPI, el `lifespan` y las tareas periódicas.
- [ ] Mover `mqtt_manager.py` a `mqtt/` y agregar el despachador, los handlers y el publisher.
- [ ] Definir los modelos pydantic de los payloads MQTT (eventos y acciones de la tabla de handlers).
- [ ] Modelos y adapters de `Reservation` y `AccessToken`; migrar el esquema.
- [ ] Crear la capa `services/` (`LockerService`, `ReservationService`, `AccessService`, `OperationService`).
- [ ] Adaptar `WebSocketHub` a FastAPI, agrupar por reserva y exponerlo como endpoint.
- [ ] Implementar los endpoints del FE web: disponibilidad, reservar, consultar, generar token, cancelar.
- [ ] Extender `DBConnector` para escrituras con **transacciones** (CU-4 marca el token usado y cambia el locker en una sola transacción) y agregar `create`, `update` y `delete` al adapter base.
- [ ] Alinear el tipo de `params` en `DBConnector.run_query` (hoy es `Dict`) con `get_by_key`, que pasa una tupla.
- [ ] Alerta en el log por `ACCESS_DENIED` repetidos (5 en 2 minutos).
- [ ] Migrar los scripts de `tests/` a pytest con fixtures en `conftest.py`.
- [ ] Dockerfile del backend y servicio en `docker-compose.yml`.

Las decisiones de negocio están en [USE_CASES.md](USE_CASES.md#decisiones).
