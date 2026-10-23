# Arquitectura del backend — Smart Locker

Este documento resume las decisiones de diseño del backend. Distingue lo que ya está implementado de lo que está planeado. Lo que el backend debe hacer está en [USE_CASES.md](USE_CASES.md).

## Resumen

El backend tiene **dos canales que no se tocan**, y cada uno corre en su propio proceso:

- **API REST**: atiende al FE web de reservas (reservar, consultar, cancelar, generar el token de apertura). Es web pura y no sabe nada de MQTT.
- **Worker MQTT**: atiende al ESP32. Recibe sus eventos (se ingresó un token, terminó un depósito, falló una operación) y le responde qué acción ejecutar. El locker gobierna los pasos físicos; el backend le dice qué hacer.

Los dos comparten la base de datos y el código de negocio (`services/`, `adapters/`, `models/`), pero corren por separado.

```
FE web ──REST──▶ ┌────────────┐                    ┌───────────────┐ ◀──MQTT──▶ ESP32
                 │ API REST   │                    │ Worker MQTT   │
                 │ (FastAPI)  │                    │ (paho)        │
                 └─────┬──────┘                    └───────┬───────┘
                       │ routers → services   handlers → services │
                       └──────────────▶ MySQL ◀────────────────────┘
```

## Decisión: dos procesos

Cada canal tiene necesidades distintas que no se cruzan:

- **REST nunca publica en MQTT.** Todas las acciones hacia el ESP32 son respuestas a eventos del propio ESP32, así que el worker maneja todo lo que entra y sale por MQTT.
- **El worker nunca habla con el FE web.** El FE se entera de los cambios consultando el estado cada pocos segundos (CU-3). La base de datos es la única fuente de verdad, así que los procesos no necesitan comunicarse entre sí.
- **Cada proceso es más simple.** El worker es Python normal y síncrono: paho llama a los handlers y los handlers llaman a los servicios. La API usa FastAPI con endpoints `def` normales.
- **Se pueden reiniciar, depurar y desplegar por separado.**

**Alternativa descartada:** un solo proceso con FastAPI y el cliente MQTT juntos, con un WebSocket para notificar al FE en tiempo real. Obligaba a coordinar el hilo de paho con el event loop de asyncio, y el WebSocket solo aportaba inmediatez, algo que la consulta periódica cubre casi igual.

### Si algún día REST necesita mandar algo al ESP32

Por ejemplo, un "calibrar locker" desde un panel. La API crearía **su propio publisher MQTT**, uno que solo publique, con su propio `client_id` y permiso en el ACL. El servicio recibiría ese publisher igual que lo recibe en el worker. No hace falta compartir el `MQTTManager` entre procesos.

### Si algún día se quiere tiempo real en el FE

El worker publicaría un aviso en un tópico interno del mismo broker (por ejemplo `smart-locker/internal/reservation/{id}`), la API se suscribiría y lo empujaría por WebSocket. Hoy no hace falta.

## Capas y regla de dependencias

```
worker/handlers.py ──import──▶ services/ ◀──import── api/routers.py
                                   │
                                   ▼
                               adapters/ ──▶ db/
```

| Capa | Responsabilidad | Conoce MQTT/HTTP |
|---|---|---|
| `api/` | Proceso de la API: app de FastAPI y routers. Traducen HTTP a llamadas a servicios | HTTP |
| `worker/` | Proceso del worker: `MQTTManager`, despachador, handlers y publisher. Traducen MQTT a llamadas a servicios | MQTT |
| `services/` | Lógica de negocio | **No** |
| `adapters/` | Acceso a datos por entidad, genérico sobre modelos de pydantic | No |
| `db/` | Conector de MySQL | No |
| `models/` | Modelos de pydantic y configuración | No |

**Regla:** `services/` nunca importa de `worker/` ni de `api/`. Si en un servicio aparece `import paho`, un tópico o un `Request` de FastAPI, algo está en la capa equivocada.

### Servicios como clases con dependencias inyectadas

Los servicios son clases que reciben sus dependencias (adapters, publisher) en `__init__`. Cada proceso los construye al arrancar. Es el mismo patrón que `LockerAdapter(connector)` y permite usar dependencias falsas en los tests.

Se eligieron clases en lugar de funciones que reciben las dependencias como parámetros porque esas dependencias habría que pasarlas en cada llamada desde cada handler y router. La clase las recibe una sola vez.

Reglas:

1. **Un servicio por responsabilidad del dominio**, no uno que lo haga todo.
2. **Las dependencias se construyen afuera** (al arrancar cada proceso), nunca dentro del servicio.
3. **Sin ciclos entre servicios.**
4. **Lógica pura en funciones sueltas.** Transiciones de estado, validaciones y cálculos no necesitan `self`.

### Servicios planeados

| Servicio | Proceso | Casos de uso | Dependencias |
|---|---|---|---|
| `LockerService` | API | CU-1 | `LockerAdapter` |
| `ReservationService` | API | CU-2, CU-3, CU-4a, CU-9 | `LockerAdapter`, `ReservationAdapter`, `AccessTokenAdapter` |
| `AccessService` | Worker | CU-4 | `LockerAdapter`, `AccessTokenAdapter`, publisher |
| `OperationService` | Worker | CU-5, CU-6, CU-7, CU-8, CU-11 | `LockerAdapter`, `ReservationAdapter` |
| `ReservationService` | Worker | CU-10 | (el mismo servicio, solo para expirar reservas) |

## Flujos

### API REST — peticiones del FE web

```
FE web → REST → router → service → DB (consulta o guarda)
              ← respuesta HTTP
```

### Worker MQTT — eventos del ESP32

```
ESP32 → MQTT → dispatch → handler → service → DB (actualiza estado)
                                           └→ publisher → MQTT → ESP32 (solo en TOKEN_ENTERED)
```

El handler **no publica ni decide**: traduce el mensaje a una llamada de servicio. Quien decide qué responder y lo publica es el servicio, con el publisher que se le inyectó.

### Tareas periódicas

Expirar reservas sin depósito (CU-10) y revertir operaciones colgadas (CU-11) no los dispara ningún mensaje. Los ejecuta el **worker** cada minuto, en el mismo ciclo donde atiende MQTT.

### Ciclo completo de un depósito

```
1. FE web   POST reserva                 → API asigna locker: available → reserved
2. FE web   POST token de apertura       → API crea AccessToken(DEPOSIT)
3. Usuario  ingresa el token en el FE local del ESP32
4. ESP32    session/event  TOKEN_ENTERED → worker valida, marca el token usado,
                                           reserved → depositing
5. worker   session/action/locker/{id}  START_DEPOSIT
6. ESP32    abre, detecta paquete, espera que cierre la puerta
7. ESP32    session/event/locker/{id}  DEPOSIT_COMPLETED
8. worker   depositing → occupied
9. FE web   (consulta cada 5 s) ve el nuevo estado
```

La recogida es igual con un token `PICKUP`, `START_PICKUP` y `PICKUP_COMPLETED`, que termina en `available`. Los fallos están en [USE_CASES.md](USE_CASES.md#cu-7--operación-fallida).

El publish es "dispara y olvida": que `publish` regrese `True` solo significa que el mensaje se encoló. Como el protocolo no tiene ACK, si un `START_*` se pierde lo detecta CU-11.

## Dos procesos escribiendo en la misma DB

La API y el worker pueden cambiar el mismo locker casi al mismo tiempo. Por ejemplo, el usuario cancela (API) justo cuando ingresa su token en el locker (worker). Para que no se pisen:

- **Cambios de estado condicionales.** Se actualiza solo si el estado sigue siendo el esperado, y se revisa cuántas filas cambiaron:

  ```sql
  UPDATE locker SET status = 'depositing' WHERE id = %s AND status = 'reserved'
  ```

  Si cambió 0 filas, otro proceso ganó y la operación se rechaza.
- **Transacciones** cuando un caso de uso cambia más de una tabla. Por ejemplo, CU-4 marca el token como usado y cambia el locker: o se hacen las dos cosas o ninguna.

## Worker MQTT

### Despachador y handlers

Los handlers son métodos de una clase que recibe los servicios en `__init__`. Esa clase expone `dispatch`, que elige el handler según el tópico usando `mqtt.topic_matches_sub` (entiende los wildcards `+` y `#`):

```python
class MQTTEventHandlers:

    def __init__(self, access_service, operation_service) -> None:
        self.access_service = access_service
        self.operation_service = operation_service

        self.routes = {
            "smart-locker/session/event": self.on_session_event,
            "smart-locker/session/event/locker/+": self.on_session_locker_event,
            "smart-locker/locker/+/event": self.on_locker_event,
        }

    def dispatch(self, topic: str, payload: str) -> None:
        for pattern, handler in self.routes.items():
            if mqtt.topic_matches_sub(pattern, topic):
                return handler(topic, payload)
        print(f"[MQTT] No handler for '{topic}'")
```

Cada handler hace siempre lo mismo: **sacar datos del tópico, validar el payload con pydantic, elegir el método según `type` y llamar al servicio.**

```python
    def on_session_event(self, topic: str, payload: str) -> None:
        event = TokenEnteredEvent.model_validate_json(payload)
        self.access_service.token_entered(event.session_id, event.token)
```

Eventos por tópico (protocolo congelado del ESP32):

| Tópico | `type` | Payload |
|---|---|---|
| `smart-locker/session/event` | `TOKEN_ENTERED` | `type`, `sessionId`, `token` |
| `smart-locker/session/event/locker/{id}` | `DEPOSIT_COMPLETED`, `PICKUP_COMPLETED` | `type`, `sessionId` |
| `smart-locker/session/event/locker/{id}` | `OPERATION_FAILED` | `type`, `sessionId`, `reason` |
| `smart-locker/locker/{id}/event` | `LOCKER_RECOVERED` | `type` |

### Publisher

Expone métodos de dominio. Los tópicos y los formatos de payload quedan encapsulados aquí, así que el servicio solo ve `start_deposit(locker_id, session_id)`.

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

### `MQTTManager`

Ya implementado, con **mTLS**: `tls_set` recibe el CA y además el certificado y la llave del backend (`smart-locker-backend`). El broker exige certificado de cliente (`require_certificate true`) y usa su CN como usuario para el ACL.

Cambios que necesita para el worker:

- **Handler síncrono.** Hoy entrega cada mensaje a un event loop de asyncio. En el worker basta con llamar al handler directamente.
- **Un solo hilo.** En lugar de `loop_start()`, que levanta un hilo aparte, el worker llama a `client.loop()` en su propio ciclo. Así, mensajes MQTT y tareas periódicas corren en el mismo hilo y nunca usan la conexión a la DB al mismo tiempo.
- **Sesión persistente** (`client_id` fijo y `clean_session=False`). Si el worker se reinicia, el broker le guarda los mensajes QoS 1 que lleguen mientras está abajo y se los entrega al volver.

El ciclo del worker queda así:

```python
while True:
    mqtt_manager.loop(timeout=1.0)      # atiende los mensajes que hayan llegado
    if time_for_periodic_tasks():
        reservation_service.expire_reservations()        # CU-10
        operation_service.revert_stalled_operations()    # CU-11
```

## API REST

- Endpoints con `def` normal (no `async`). FastAPI los ejecuta en un pool de hilos.
- Como varios requests pueden atenderse a la vez en hilos distintos, **cada request usa su propia conexión a la DB** (una dependencia de FastAPI que la abre y la cierra). Una conexión de MySQL no se debe compartir entre hilos.
- El código de reserva viaja en el header `Authorization`, no en la URL.

Endpoints planeados:

| Endpoint | Caso de uso |
|---|---|
| `GET /lockers/availability` | CU-1 |
| `POST /reservations` | CU-2 |
| `GET /reservations/current` | CU-3 |
| `POST /reservations/current/access-token` | CU-4a |
| `DELETE /reservations/current` | CU-9 |

## Ejecución

Dos procesos, cada uno en su contenedor:

```
uvicorn smart_locker.api.main:app --host 0.0.0.0 --port 8000
python -m smart_locker.worker
```

- **Worker: una sola instancia, siempre.** Con dos, cada evento se procesaría dos veces.
- **API: puede tener varias instancias** si hiciera falta, porque no guarda estado en memoria. Todo está en la DB.

## Estructura del proyecto

```
backend/
├── pyproject.toml          # paquete instalable (hatchling, uv package = true)
├── uv.lock
├── ARCHITECTURE.md
├── USE_CASES.md
├── smart_locker/
│   ├── api/                # (planeado) proceso 1: FastAPI + routers
│   ├── worker/             # (planeado) proceso 2: MQTTManager, handlers, publisher
│   ├── services/           # (planeado) lógica de negocio, compartida
│   ├── adapters/           # acceso a datos genérico, compartido
│   ├── db/                 # conector MySQL y excepciones
│   ├── models/             # modelos pydantic y configuración
│   ├── exceptions.py       # excepciones de dominio
│   ├── mqtt_manager.py     # se moverá a worker/
│   └── web_socket_hub.py   # ya no se usa; se elimina
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
    expires_at DATETIME NOT NULL,
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

`status_since` sirve para detectar operaciones colgadas (CU-11) y para el tiempo de vida de `occupied` (72 h).

## Pendientes

En orden sugerido:

- [ ] Modelos: `status_since` en `LockerModel`, `ReservationModel`, `AccessTokenModel` y `FailureReason`.
- [ ] Migrar el esquema (tablas `reservation` y `access_token`, columna `status_since`).
- [ ] Extender `DBConnector` para escrituras y transacciones, y alinear el tipo de `params` en `run_query` (hoy es `Dict`) con `get_by_key`, que pasa una tupla.
- [ ] Agregar `create` y `update` al adapter base; crear `ReservationAdapter` y `AccessTokenAdapter`.
- [ ] Crear la capa `services/` (`LockerService`, `ReservationService`, `AccessService`, `OperationService`).
- [ ] Worker: mover `mqtt_manager.py` a `worker/` con los cambios de arriba; modelos de payload MQTT, handlers, publisher y el ciclo principal.
- [ ] API: agregar `fastapi` y `uvicorn` a `pyproject.toml`; app, routers y conexión a la DB por request.
- [ ] Alerta en el log por `ACCESS_DENIED` repetidos (5 en 2 minutos).
- [ ] Eliminar `web_socket_hub.py` y la dependencia `websockets`.
- [ ] Migrar los scripts de `tests/` a pytest con fixtures en `conftest.py`.
- [ ] Dockerfiles de la API y del worker, y sus servicios en `docker-compose.yml`.

Las decisiones de negocio están en [USE_CASES.md](USE_CASES.md#decisiones).
