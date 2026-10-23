# Casos de uso del backend — Smart Locker

Este documento delimita qué hace el backend. De aquí salen los servicios, los endpoints y los modelos descritos en [ARCHITECTURE.md](ARCHITECTURE.md).

El protocolo MQTT con el ESP32 está congelado y documentado en `IoT-FCiencias-2026/SmartLocker/smart-locker-system-design-status.md`. Este documento no lo cambia, solo define cómo reacciona el backend.

## Contexto

### Dos frontends

| | FE local del ESP32 | FE web del backend |
|---|---|---|
| Dónde corre | Lo sirve el ESP32 en `192.168.4.1` (AP `SmartLocker`) | Lo sirve este servidor |
| Para qué | Ingresar el token **frente al locker** y seguir la operación física | Reservar, consultar el pedido y generar tokens de apertura |
| Con quién habla | Solo con el ESP32 (HTTP + WS) | Con el backend (solo REST) |

El backend **nunca habla con el FE local**. Todo lo que pasa frente al locker le llega por MQTT.

### Regla de reparto

> El backend decide (qué locker, si el token es válido, si es depósito o recogida). El ESP32 ejecuta la operación física una vez autorizada.

Una vez que el backend publica `START_DEPOSIT` o `START_PICKUP`, la autorización es final: no hay ACK ni cancelación.

### Vocabulario

- **Reserva (`Reservation`)**: entidad persistente del backend. Dura desde que el usuario reserva hasta que recoge, cancela, expira o falla. Se identifica ante el usuario con un **código de reserva** secreto.
- **Token de apertura (`AccessToken`)**: código efímero que el usuario ingresa en el FE local para abrir el locker. Es de **un solo uso**, tiene un propósito (`DEPOSIT` o `PICKUP`) y caduca.
- **`sessionId`**: sesión efímera del navegador frente al locker, generada por el ESP32. **No es una reserva.** El backend solo la usa para responder al `TOKEN_ENTERED` correcto.

## Modelo

```
Reservation (persistente)                AccessToken (efímero, un solo uso)
─────────────────────────                ──────────────────────────────────
id                               1 ── N  id
code        (secreto, alta entropía)     reservation_id
locker_id                                token
status                                   purpose      DEPOSIT | PICKUP
created_at                               expires_at
expires_at  (48 h para depositar)        used_at
closed_at                                created_at
```

El **código de reserva** es la credencial del usuario ante el FE web: quien lo tiene puede consultar el pedido, generar tokens y cancelar. Debe tener alta entropía, por ejemplo `secrets.token_urlsafe(16)`.

### Tokens de apertura

- Se generan **bajo demanda** desde el FE web, no al reservar.
- El backend decide el propósito según el estado del locker: `reserved` → `DEPOSIT`, `occupied` → `PICKUP`.
- Vigencia corta: **15 minutos**.
- Generar uno nuevo invalida cualquier otro token vigente de la misma reserva.
- Formato: **8 caracteres alfanuméricos**, sin caracteres ambiguos (`0/O`, `1/I/l`).
- Se marcan como usados (`used_at`) **al validarse**, en la misma transacción que el cambio de estado del locker. Si la operación falla después, el usuario genera otro.

### Estados del locker (`LockerStatus`)

```
available ──CU-2──▶ reserved ──CU-4──▶ depositing ──CU-5──▶ occupied ──CU-4──▶ picking_up ──CU-6──▶ available
    ▲                 │  ▲                  │                   ▲                    │
    │      CU-9/CU-10 │  └── CU-7 / CU-11 ──┘                   └─── CU-7 / CU-11 ───┘
    └─────────────────┘

depositing | picking_up ──CU-7 (DOOR_LEFT_OPEN)──▶ unavailable ──CU-8──▶ available
```

### Estados de la reserva

| Estado | Cuándo |
|---|---|
| `active` | Desde que se crea hasta que termina por cualquier camino |
| `completed` | Recogida completada (CU-6) |
| `cancelled` | El usuario cancela (CU-9) |
| `expired` | Pasó el tiempo de reserva sin depositar (CU-10) |
| `failed` | `DOOR_LEFT_OPEN` (CU-7) |

## Casos de uso

| # | Caso de uso | Disparador | Efecto |
|---|---|---|---|
| CU-1 | Consultar disponibilidad | FE web, REST | — |
| CU-2 | Reservar | FE web, REST | El backend asigna un locker `available` → `reserved` y crea la `Reservation` |
| CU-3 | Consultar pedido | FE web, REST | — |
| CU-4a | Generar token de apertura | FE web, REST | Crea un `AccessToken` e invalida los anteriores |
| CU-4 | Validar token ingresado en el locker | MQTT `TOKEN_ENTERED` | `START_DEPOSIT`, `START_PICKUP` o `ACCESS_DENIED` |
| CU-5 | Depósito completado | MQTT `DEPOSIT_COMPLETED` | `depositing → occupied` |
| CU-6 | Recogida completada | MQTT `PICKUP_COMPLETED` | `picking_up → available`, reserva `completed` |
| CU-7 | Operación fallida | MQTT `OPERATION_FAILED` | Según `reason` |
| CU-8 | Locker recuperado | MQTT `LOCKER_RECOVERED` | `unavailable → available` |
| CU-9 | Cancelar reserva | FE web, REST | `reserved → available`, reserva `cancelled` |
| CU-10 | Expirar reserva sin depósito | Tarea periódica | `reserved → available`, reserva `expired` |
| CU-11 | Operación colgada | Tarea periódica | Revertir `depositing` / `picking_up` |

El FE web se entera de los cambios de estado consultando periódicamente (CU-3). El backend no empuja notificaciones.

### CU-1 — Consultar disponibilidad

Devuelve cuántos lockers están `available`. No expone qué reservas hay.

### CU-2 — Reservar

1. El backend elige un locker `available`. El usuario no elige; esto permite agregar reglas después (tamaños, etc.) sin tocar el ESP32.
2. Lo marca `reserved` y crea la `Reservation` con su código y `expires_at`.
3. Responde con el código de reserva y el número de locker.

Si no hay lockers disponibles, responde `409 Conflict`.

### CU-3 — Consultar pedido

Con el código de reserva, el FE web obtiene el estado actual por REST.

- Mientras la página de "Consultar mi pedido" está abierta, el FE repite la consulta cada **5 segundos**. Así el seguimiento es casi en tiempo real sin que el backend tenga que empujar nada.
- El FE deja de consultar cuando la reserva termina (`completed`, `cancelled`, `expired`, `failed`).
- El código de reserva va en un header (`Authorization`), no en la URL, para que no quede en los logs.
- Si el plazo de recogida venció (ver CU-5), la consulta lo indica con un mensaje.

### CU-4a — Generar token de apertura

1. Con el código de reserva, el usuario pide un token desde el FE web.
2. El backend valida que el locker esté en `reserved` (token `DEPOSIT`) o `occupied` (token `PICKUP`). En otro estado responde `409 Conflict`.
3. Invalida los tokens vigentes de la reserva, crea uno nuevo y lo devuelve con su `expires_at`.

### CU-4 — Validar token ingresado en el locker

Entrada: `smart-locker/session/event`

```json
{ "type": "TOKEN_ENTERED", "sessionId": "ffe7498d", "token": "K7M2Q9XA" }
```

1. Buscar un `AccessToken` con ese valor, sin `used_at` y no expirado.
2. **Válido:** en una sola transacción, marcar `used_at` y cambiar el locker (`reserved → depositing` o `occupied → picking_up`). Después publicar en `smart-locker/session/action/locker/{lockerId}`:

   ```json
   { "type": "START_DEPOSIT", "sessionId": "ffe7498d" }
   ```

   o `START_PICKUP` con la misma forma.
3. **Inválido** (no existe, expirado o ya usado): publicar en `smart-locker/session/action`:

   ```json
   { "type": "ACCESS_DENIED", "sessionId": "ffe7498d", "reason": "INVALID_CREDENTIALS" }
   ```

   El `reason` es siempre `INVALID_CREDENTIALS`, para no revelar si el token existió.

**Duplicados:** el ESP32 reintenta `TOKEN_ENTERED` si no pudo publicarlo, y QoS 1 puede entregarlo dos veces. Como el token se marca usado en la primera validación, un duplicado recibe `ACCESS_DENIED`. El ESP32 lo ignora si la sesión ya está activa.

**Fuerza bruta:** el backend no puede bloquear, porque solo ve "el ESP32" y cada intento trae un `sessionId` nuevo. La defensa es:

1. La entropía y la vigencia del token: 8 alfanuméricos, 15 minutos, como mucho un token vigente por locker.
2. El backend registra una alerta en el log si hay **5 `ACCESS_DENIED` en 2 minutos**. No bloquea nada. Un token inválido no está ligado a ninguna reserva, así que esta alerta no puede mostrarse en la consulta de pedido.

### CU-5 — Depósito completado

Entrada: `smart-locker/session/event/locker/{lockerId}` con `DEPOSIT_COMPLETED`.

`depositing → occupied`. La reserva sigue `active`; el usuario generará un token `PICKUP` cuando vaya a recoger.

**Tiempo de vida de `occupied`: 72 horas** desde el depósito (`status_since` del locker al pasar a `occupied`). Si vence, no cambia ningún estado y el usuario todavía puede recoger: la consulta de pedido (CU-3) muestra un mensaje de plazo vencido. Qué hacer con un paquete no recogido se resuelve fuera del sistema.

### CU-6 — Recogida completada

Entrada: `smart-locker/session/event/locker/{lockerId}` con `PICKUP_COMPLETED`.

`picking_up → available`. La reserva pasa a `completed`.

### CU-7 — Operación fallida

Entrada: `smart-locker/session/event/locker/{lockerId}`

```json
{ "type": "OPERATION_FAILED", "sessionId": "a7f3", "reason": "DOOR_LEFT_OPEN" }
```

| `reason` | Locker | Reserva |
|---|---|---|
| `OPEN_TIMEOUT` (depósito) | `depositing → reserved` | Sigue `active`, el usuario genera otro token |
| `OPEN_TIMEOUT` (recogida) | `picking_up → occupied` | Sigue `active` |
| `PACKAGE_NOT_DETECTED` | `depositing → reserved` | Sigue `active` |
| `PACKAGE_NOT_REMOVED` | `picking_up → occupied` | Sigue `active` |
| `UNKNOWN_SESSION` | Revierte al estado previo (`reserved` u `occupied`) | Sigue `active` |
| `DOOR_LEFT_OPEN` | `unavailable` | `failed`. El contenido es irrelevante: la responsabilidad es del usuario |

El estado previo se deduce del estado actual: `depositing` vuelve a `reserved` y `picking_up` vuelve a `occupied`.

`UNKNOWN_SESSION` significa que la operación física **no empezó**. Ocurre cuando el `START_*` llegó después de que la sesión del ESP32 expiró (30 s), cuando el ESP32 se reinició entre el `TOKEN_ENTERED` y el `START_*`, o ante un `START_*` duplicado. Este último no debería ocurrir porque el token se marca usado antes de publicar.

### CU-8 — Locker recuperado

Entrada: `smart-locker/locker/{lockerId}/event` con `LOCKER_RECOVERED`.

`unavailable → available`. Si se recuperó es porque está listo para operar.

Hoy el firmware no lo emite: la recuperación necesita el sensor de puerta real (fase C). Mientras tanto, un locker `unavailable` requiere una revisión física, y su estado se ajusta manualmente en la DB. Esa revisión queda fuera del sistema.

### CU-9 — Cancelar reserva

Con el código de reserva. Solo se permite en `reserved`: `reserved → available`, reserva `cancelled`, tokens vigentes invalidados. En otro estado responde `409 Conflict`.

### CU-10 — Expirar reserva sin depósito

El usuario tiene **48 horas** desde que reserva para depositar. Una tarea periódica busca reservas `active` con locker `reserved` y `expires_at` vencido: `reserved → available`, reserva `expired`.

### CU-11 — Operación colgada

Como no hay ACK, un `START_*` puede perderse y el backend se quedaría en `depositing` o `picking_up` para siempre.

Una tarea periódica revierte las operaciones que llevan más de **12 minutos** sin `*_COMPLETED` ni `OPERATION_FAILED` (`depositing → reserved`, `picking_up → occupied`). El umbral es mayor que el `ACTIVE_TIMEOUT` del ESP32 (10 min), para no revertir una operación que todavía está en curso.

Para esto el locker necesita guardar desde cuándo está en su estado actual (`status_since`).

## Decisiones

- Reserva sin depósito: 48 horas (CU-10).
- Tiempo de vida de `occupied`: 72 horas; al vencer solo se muestra un mensaje en la consulta de pedido (CU-5, CU-3).
- Locker `unavailable` sin `LOCKER_RECOVERED`: revisión física y ajuste manual, fuera del sistema (CU-8).
- Alerta por `ACCESS_DENIED`: se registra en el log (CU-4).
