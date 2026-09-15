# Reservas de visitas: cambios, decisiones y limitaciones

## Cómo se prueba

```bash
.venv\Scripts\python.exe -m pytest tests\ -q   # 31 pruebas verdes
```

`tests/test_reservations_availability.py` usa las rutas reales contra una
SQLite desechable (`frontend_marketplace_moda/scripts/qa_backend.py`); cada
prueba arma sus propios datos de catálogo y sucursal para no depender del
estado compartido de la suite.

## Cambios por archivo

- `web/router.py`
  - `GET /reservations/availability` acepta `quantities` (aligned, opcional) y
    documenta el contrato.
  - `POST /reservations` acepta `client_key` (idempotencia) y la respuesta
    201 incluye `branch_name`.
  - `GET /reservations/admin/all` enriquece cada fila con `branch_name`,
    `user_name` (`first_name + " " + last_name`; `UserModel` no tiene
    `full_name`) y `user_email`, mediante consultas por lotes (sin N+1), y
    acepta `q`, `date_from`, `date_to`, `order` (`scheduled_at`/`created_at`),
    `direction` (`asc`/`desc`). El cliente normal no puede leer el panel (403).
- `application/use_cases/consultar_disponibilidad.py`
  - Disponible = publicada **y** stock ≥ cantidad pedida. Respuesta con
    `requested` y `reason` diferenciado:
    «La prenda ya no está publicada.» / «Sin unidades en esta sucursal.» /
    «Solo hay N unidad(es) y pediste M.» — evita que el cliente viaje al local
    para una talla que no alcanza (Hallazgo G).
- `application/use_cases/create_reserva.py`
  - `_merge_items`: agrupa variantes repetidas y aplica los límites tras la
    fusión (≤20 variantes distintas, ≤10 unidades por talla).
  - `_validar_disponibilidad`: rechaza la reserva con el detalle si la sucursal
    no cubre las cantidades.
  - **Idempotencia**: si `client_key` ya existe para el usuario, se devuelve la
    misma reserva; ante `IntegrityError` (dos envíos simultáneos con la misma
    clave) se hace rollback y se re-lee la persistida. Estrategia transaccional
    documentada: sin bloqueos permanentes, reintentos de un mismo intento no
    duplican la visita (Hallazgo F/I).
  - Tracking inicial: «Reserva registrada; pendiente de confirmacion de la
    sucursal.» y bitácora `reservas.created`.
- `infrastructure/http/schemas.py`
  - `CrearReservaRequest.client_key` (máx. 64); `items` 1..20 ítems y cada uno
    `quantity` 1..10 (validación Pydantic como primera barrera).
- `infrastructure/persistence/models/reserva.py`
  - Columna `client_key` (String(64), nullable) + `UniqueConstraint(user_id,
    client_key)`: permite varias reservas nulas por usuario (sin clave) y una
    sola por clave.
- `infrastructure/persistence/repositories/reserva_repository.py`
  - `get_by_client_key(user_id, key)` para idempotencia.
  - `list()` con `q` (email/nombre/id por `func.cast`), `date_from`, `date_to`,
    `order`, `direction`; solo une `UserModel` cuando hay búsqueda.
- `application/use_cases/list_reservas.py`
  - Propaga los nuevos filtros al repositorio.
- `alembic/versions/20260916_0006_reservations_client_key.py` (nueva)
  - Añade `client_key` y la constraint única. `down_revision = "20260912_0005"`.
  - **No ejecutada** contra la base real; `qa_backend.py` la cubre con
    `create_all()`. No se tocó producción.

## Pruebas agregadas
- Cantidades vs. stock (alcanza / no alcanza / alineación inválida), disponibles
  y con motivo.
- Fusión de duplicados (4+3 → 7 en una línea) e idempotencia (misma clave →
  misma reserva, una sola fila en el listado).
- Panel administrativo: cliente sin permisos → 403; enriquecido (sucursal,
  email, nombre); filtro por rango de fechas con `direction`, y exclusión fuera
  del rango.

## Limitaciones
- La migración 0006 debe aplicarse al universo que corresponda (QA/local) antes
  de desplegar el código que usa `client_key`; en la base compartida de QA la
  columna se crea sola con `create_all()`.
- La lista de prendas es del lado del cliente (sessionStorage); el backend solo
  ve la visita confirmada (por diseño del caso de uso CU-14).
- No se editaron horario ni ítems de una reserva existente: el panel solo
  confirma, prepara, atiende o cancela.