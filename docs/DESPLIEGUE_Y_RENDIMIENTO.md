# Despliegue y rendimiento — base de datos y procesos

Este documento explica **por qué** el backend está configurado así y **qué tiene que hacer el usuario
a mano** en las variables de Railway. No contiene ninguna cadena de conexión real, ninguna
contraseña y ningún token: todo lo sensible viaja por variable de entorno y se escribe únicamente en
el panel de Railway.

Ningún cambio descrito aquí altera el API: mismas rutas, mismos códigos de estado, mismo envoltorio
`{success, message, data}` y los mismos mensajes en español.

---

## 1. Pool de conexiones

`src/infrastructure/database/session.py` construye el engine con el pool dimensionado desde
`settings`, y solo cuando la URL es PostgreSQL.

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `DB_POOL_SIZE` | `5` | Conexiones permanentes por proceso |
| `DB_MAX_OVERFLOW` | `5` | Conexiones extra que el pool abre en picos y luego cierra |
| `DB_POOL_RECYCLE` | `1800` | Segundos antes de descartar y reabrir una conexión |
| `DB_POOL_TIMEOUT` | `30` | Espera máxima por una conexión libre antes de fallar |

`pool_pre_ping` sigue activado siempre.

### Por qué 5 + 5 y no más

El total real de conexiones es **réplicas × workers × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`)**.

El plan gratuito de Supabase (cómputo Nano) admite **60 conexiones directas** por el puerto 5432, y
esas 60 no son todas de la aplicación: Auth, Storage, PostgREST, Realtime y el propio health checker
de Supabase consumen parte, más las reservadas para superusuario. La guía de *Connection management*
de Supabase recomienda no pasar del **40 % de `max_connections`** cuando PostgREST está en uso, es
decir **24 conexiones** para el backend.

| Escenario | Total | % de 60 | Veredicto |
|---|---|---|---|
| Antes: 1 worker × (5 + 10) | 15 | 25 % | Correcto, pero con un solo proceso |
| 2 workers × (5 + 10) — pool sin tocar | 30 | 50 % | **No**: subir workers sin bajar el pool es un error |
| 2 workers × (10 + 10) | 40 | 67 % | **No** |
| **2 workers × (5 + 5) — configuración actual** | **20** | **33 %** | **Seguro** |

Diez conexiones por proceso sobran: la consulta real del catálogo tarda 40 ms, así que cada proceso
sostiene del orden de 250 consultas por segundo antes de saturar el pool. El cuello de botella nunca
fue la base.

`tests/unit/infrastructure/test_db_pool.py` incluye un candado
(`test_el_total_de_conexiones_entra_en_el_plan_gratuito_de_supabase`) que falla si alguien sube el
pool por encima de ese presupuesto.

### Por qué `pool_recycle = 1800`

Antes el valor era `-1`: las conexiones no se reciclaban nunca. Supabase cierra las conexiones
ociosas del lado del servidor, así que la primera petición después de un rato de calma encontraba una
conexión muerta; `pool_pre_ping` lo detectaba y reabría, pero pagando un `SELECT 1` fallido y una
reconexión. Reciclar a 30 minutos elimina la mayoría de esos casos.

### Por qué el pool no se aplica a SQLite

`max_overflow` y `pool_timeout` son argumentos de `QueuePool`. Para `sqlite+pysqlite:///:memory:`
SQLAlchemy elige `SingletonThreadPool` y `create_engine` responde
`TypeError: Invalid argument(s) 'max_overflow'`. Como `create_engine` se ejecuta al **importar**
`session.py`, y casi toda la suite lo arrastra a través de `src.main`, ese `TypeError` no rompería
una prueba: rompería la recolección entera. Por eso `opciones_de_pool()` devuelve un diccionario
vacío cuando la URL no empieza por `postgresql`.

### Sumandos que se suelen olvidar

- El `preDeployCommand` de Alembic abre **1 conexión** con `NullPool` (`alembic/env.py`) y termina
  antes de que arranque uvicorn: no se solapa.
- Si el backend se deja corriendo **en la máquina local con el mismo `DATABASE_URL`** mientras
  Railway está arriba, suma otras 10 y el total llega a 30, por encima de las 24 recomendadas. **No
  dejar el backend local encendido durante la demostración.**
- Subir `numReplicas` en Railway multiplica todo: 2 réplicas × 2 workers × 10 = 40 conexiones, ya en
  zona de riesgo.

---

## 2. Procesos de uvicorn (`WEB_CONCURRENCY`)

`railway.json` arranca ahora con varios procesos:

```
sh -c 'exec python -m uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}'
```

Antes se arrancaba sin `--workers`, es decir **un solo proceso**: cualquier trabajo bloqueante
congelaba todo el servicio. Con 2 procesos hay aislamiento real entre peticiones.

`WEB_CONCURRENCY` permite bajarlo a `1` desde el panel de Railway **sin volver a desplegar el
código**. Es la marcha atrás más rápida si algo sale mal.

### Cuándo conviene `WEB_CONCURRENCY=1`

1. **Memoria.** Importar la aplicación cuesta ~112 MB de RSS por proceso (medido). Con 2 workers son
   ~245 MB en reposo contra ~125 MB antes. Además Pillow, al procesar una imagen, puede sumar
   200–290 MB por subida concurrente (`MAX_PIXELS = 24.000.000` en `media_storage.py`). En el plan
   **Trial de Railway el límite es 1 GB por servicio**: dos subidas simultáneas con 2 workers pueden
   provocar un *OOM kill*. En el plan **Hobby** (hasta 48 GB) no hay problema técnico.
   Alternativa a bajar workers: reducir `MEDIA_MAX_UPLOAD_MB`.
2. **Idempotencia del asistente.** `src/ventas_pagos/application/assistant_tools.py` guarda los
   `request_id` ya atendidos en un diccionario **en memoria del proceso** (TTL de 60 s). Con 2
   workers, un reintento que caiga en el otro proceso no verá el `request_id` anterior: regenerará el
   archivo y puede no devolver la cabecera `X-Idempotent-Replay`. El propio módulo declara esa
   política como *best-effort en memoria*, así que no es un contrato roto, pero la tasa de
   deduplicación baja a la mitad. La venta en caja (`pos_sale`) **no** está afectada: su idempotencia
   se resuelve contra la base.

No hay ningún otro estado global compartido entre procesos: no hay caché en memoria, ni planificador,
ni hilos de fondo preexistentes. `MEDIA_STORAGE_DIR` es el sistema de archivos del mismo contenedor y
los nombres se generan con `uuid4().hex`, así que los workers no colisionan.

### El `preDeployCommand` de Alembic sigue siendo correcto

Railway ejecuta el pre-deploy **una sola vez por despliegue**, en un contenedor efímero, antes de que
arranque ninguna réplica. `--workers` es un detalle interno del `startCommand` y Railway ni lo ve:
Alembic no corre dos veces y no hay carrera de migraciones. Refuerzo adicional: `alembic/env.py` usa
`poolclass=NullPool`, abre una conexión, migra y la cierra. Si el pre-deploy falla, el despliegue no
avanza.

El `healthcheckTimeout` de 30 s alcanza: cada worker tarda ~2,1 s en importar la aplicación y lo
hacen en paralelo.

---

## 3. Cola de correos (`EMAIL_*`)

`settings.py` declara tres ajustes que usa el envío de correo fuera del request:

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `EMAIL_BACKGROUND` | `true` | Enviar el correo después de responder, en segundo plano |
| `EMAIL_QUEUE_SIZE` | `100` | Tope de correos encolados |
| `EMAIL_WORKERS` | `2` | Hilos dedicados al envío |

Motivo: solo el saludo TCP+TLS con Gmail cuesta **1,45 s medidos**, antes del login y del envío.
Enviar dentro del request no solo sumaba ~2,5 s a la respuesta, además retenía una conexión de base
de datos durante todo ese tiempo.

`EMAIL_BACKGROUND=false` vuelve al envío en línea. Es el interruptor que necesitan las pruebas, que
comprueban el booleano de retorno y el evento de bitácora en la misma sesión inmediatamente después
de llamar.

---

## 4. ACCIÓN MANUAL DEL USUARIO — pasar al pooler de Supabase (puerto 6543)

**Esto no se hace desde el código.** Se cambia la variable `DATABASE_URL` en el panel de Railway.
Es opcional: con 20 conexiones la conexión directa alcanza. Conviene hacerlo si se va a subir
`WEB_CONCURRENCY`, `numReplicas` o el tamaño del pool, porque el pooler (Supavisor) admite **200
clientes** en lugar de 60.

### Formato de la cadena (solo marcadores, nunca valores reales)

Conexión **directa**, la que se usa hoy:

```
postgresql://postgres:<CONTRASENA>@db.<REFERENCIA_DEL_PROYECTO>.supabase.co:5432/postgres
```

Conexión por el **pooler en modo transacción**:

```
postgresql://postgres.<REFERENCIA_DEL_PROYECTO>:<CONTRASENA>@aws-0-<REGION>.pooler.supabase.com:6543/postgres
```

**Cambian tres cosas a la vez, no una.** Cambiar solo el puerto falla la autenticación:

1. El usuario pasa de `postgres` a `postgres.<REFERENCIA_DEL_PROYECTO>` (la referencia del proyecto
   como sufijo, separada por un punto).
2. El host pasa al dominio del pooler.
3. El puerto pasa de `5432` a `6543`.

La base sigue llamándose `postgres`. Los valores reales de `<REFERENCIA_DEL_PROYECTO>`, `<REGION>` y
`<CONTRASENA>` se copian desde *Project Settings → Database → Connection string* en el panel de
Supabase y se pegan **únicamente** en la variable de Railway. Nunca en el repositorio, ni en un chat,
ni en una captura. Si alguna vez se expusieron, hay que rotar la contraseña.

### Sentencias preparadas: por qué este backend es compatible tal cual

El modo transacción de Supavisor **no soporta sentencias preparadas del lado del servidor**. Este
backend es compatible igual porque usa `psycopg2`, que **no** las usa por omisión: interpola los
parámetros del lado del cliente. No hay que tocar ni una línea.

> Esta compatibilidad **no** se mantendría con `asyncpg` o `psycopg3`, que sí preparan sentencias y
> exigen desactivar la caché (`statement_cache_size=0` / `prepare_threshold=0`). Si algún día se
> migra el driver, hay que revisar este punto **antes** de desplegar.

Lo demás verificado contra el código:

- `with_for_update()` (en `returns_service.py` y `stock_service.py`) sigue siendo correcto: el modo
  transacción fija la conexión del servidor durante toda la transacción, así que el bloqueo de fila
  vive entero dentro de ella.
- Lo que el modo transacción sí rompe **no se usa en este repositorio**: `LISTEN`/`NOTIFY`, bloqueos
  de aviso de alcance de sesión, `SET` fuera de transacción y cursores con nombre del lado del
  servidor. Cero coincidencias.
- Con el pooler conviene mantener el pool de cliente **pequeño** (Supavisor ya agrupa): `5 + 5` sigue
  siendo la recomendación. No hay motivo para agrandarlo.

### Alembic debe seguir usando la conexión directa

Las migraciones (DDL y bloqueos de esquema) se comportan mejor en modo sesión. Si se migra
`DATABASE_URL` al pooler, conviene dejar una variable aparte con la cadena directa y que
`alembic/env.py` la prefiera cuando exista.

> Nota: `alembic.ini` trae `sqlalchemy.url = postgresql://postgres:postgres@localhost:5432/fashionstore`.
> Es un marcador local de relleno que `alembic/env.py` sobrescribe con `settings.database_url`. No es
> una credencial real y no debe confundirse con la cadena de producción.

---

## 5. Lista de verificación antes de la entrega

- [ ] `WEB_CONCURRENCY` acorde al plan de Railway (`1` si es Trial y se van a subir imágenes grandes).
- [ ] `DB_POOL_SIZE` y `DB_MAX_OVERFLOW` sin tocar, salvo que se haya recalculado el presupuesto.
- [ ] El backend local **apagado** durante la demostración, para no gastar conexiones de Supabase.
- [ ] `EMAIL_BACKGROUND` en `true` en Railway.
- [ ] Ninguna cadena de conexión, contraseña ni token en el repositorio.
