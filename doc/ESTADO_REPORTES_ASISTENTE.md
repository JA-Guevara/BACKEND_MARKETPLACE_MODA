# Estado de reportes, dashboard y asistente (backend)

Fecha: 2026-09-15 · Análisis realizado antes de modificar código.

> **Actualización 2026-09-15 (fin de tanda):** plan A, B y C **completos y
> verificados** (`pytest -q` → 36 passed). Cambios en `reports_service.py`
> (bloque `meta`, `period.*`, `units_sold`, `comparison`, `low_stock_variants`,
> `reservations_by_status`, `payment_methods`, filtros y `_window` naive/aware,
> `_projection` con `meta`), `reports_ai.py`, `exporter.py`, `settings.py`
> (`ai_timeout`, `ai_max_tokens`, `report_export_max_rows`,
> `low_stock_threshold=5`), `alembic/env.py` (importa `ReservationModel`),
> `schemas.py` (`ReportFilters/InterpretRequest/ExplainRequest/InsightsRequest`),
> N+1 de `/commerce/admin/stock` corregido. Desde esta fecha el dashboard
> **sin** `date_from/date_to` cubre TODO el historial (sin ventana por defecto).

## 1. Lo que existe y está realmente conectado

La implementación funcional vive en `src/ventas_pagos` (commerce + analítica) y usa
`src/usuarios_catalogo` (catálogo) e `src/inventario_sucursales` (sucursales).

| Endpoint | Método | Permiso | Ubicación |
|---|---|---|---|
| `/api/v1/analytics/dashboard` | GET | `dashboard.read` | `src/ventas_pagos/web/router.py:206` |
| `/api/v1/analytics/insights` | POST | `dashboard.read` | `router.py:213` (cuerpo opcional de filtros) |
| `/api/v1/analytics/assistant/interpret` | POST | `dashboard.read` | `router.py:231` (NUEVO) |
| `/api/v1/analytics/assistant/explain` | POST | `dashboard.read` | `router.py:246` (NUEVO) |
| `/api/v1/analytics/reports/export` | GET | `dashboard.read` | `router.py:254` (NUEVO, xlsx/csv) |
| `/api/v1/commerce/assistant` | POST | solo auth (login) | `router.py:77` |
| `/api/v1/commerce/branches` | GET | auth | `router.py:45` |
| `/api/v1/commerce/cart`, `/orders`, `/admin/*` | varios | `commerce.*`/`stock.*` | `router.py` |
| `/api/v1/bulk/*` (export/import XLSX de catálogo) | GET/POST | allow-list | `src/shared/bulk` |

Cálculo real: `src/ventas_pagos/application/reports_service.py` (`ReportsService.dashboard`).
Devuelve: `orders`, `paid_orders`, `pending_orders`, `revenue`, `currency`, `products`,
`customers`, `low_stock`, `by_status`, `daily_sales`, `top_products`, `stripe_ready`,
`ai_ready`, `average_ticket`, `cancellation_rate`, `monthly_sales`,
`hourly_distribution`, `weekday_distribution`, `category_breakdown`,
`branch_performance`, `projection` y **`meta`** (período/zona/moneda/generado/cobertura),
**`period`** (`orders, paid_orders, pending_orders, revenue, units_sold, ticket_avg,
cancellation_rate`), **`units_sold`**, **`comparison`** (`previous`/`year_ago` con
`revenue_delta_pct`/`paid_delta_pct` o `base_note:"Sin base comparable"`),
**`low_stock_variants`** (variante/sucursal/talla/color/stock), **`reservations_by_status`**,
**`payment_methods`**. Filtros: `branch_id`, `category_id`, `status`, `low_stock_lt`.

`src/dashboard/` está **huérfana y vacía** (5 archivos de 0 bytes), no registrada en
`src/config/routes.py`. No duplica código en uso.

## 2. Datos procedentes

- Orden de compra: `commerce_orders` (`OrderModel`), campos total, currency, status
  (`pending_payment|paid|processing|shipped|delivered|cancelled|expired`),
  payment_status (`pending|paid|cancelled`), payment_method, items (JSON snapshot).
- Stock: `commerce_stock` (variant_id+branch_id, quantity). Low stock = `quantity < 5`
  hardcodeado en `reports_service.py:48`.
- `products`, `product_variants`, `categories`, `sizes`, `colors`, `seasons`,
  `collections`, `product_suppliers` en `src/usuarios_catalogo/.../models/catalog.py`.
- Sucursales/ciudades: `src/inventario_sucursales/.../models/organization.py`.
- Reservas: `reservations` (`ReservationModel`, estado pending/confirmed/ready/attended/
  cancelled). OJO: `alembic/env.py` **no importa ReservationModel** → autogenerate
  propondría dropear la tabla.
- Moneda única: `commerce_currency` (bob). Sin conversión; `revenue` suma todos los
  `total` sin agrupar por currency.

## 3. Errores e inconsistencias detectadas

1. **Insights ignora filtros** → **CORREGIDO**: acepta cuerpo opcional `InsightsRequest {question?, filters?}` y siempre usa ese contexto (retrocompatible sin cuerpo).
2. **Carga todo en memoria**: `select(OrderModel)` + filtros en Python. Aceptable a esta escala; sigue sin límite (dejar para escala mayor).
3. **`_window` naive vs aware** → **CORREGIDO** con `_as_utc`/`_utc_of` (naive = `America/La_Paz`; `created_at` naive = UTC).
4. **N+1 en stock admin** → **CORREGIDO**: única consulta `scalars()` + mapa `rows_by_variant`.
5. **`/commerce/assistant` sin permiso** mientras `/analytics/insights` exige `dashboard.read`: sigue pendiente de decidir (frontend gatea con `session.can`).
6. **Sin exportación analítica** → **CORREGIDO**: `GET /analytics/reports/export` (xlsx/csv, máx `report_export_max_rows`, CSV con metadatos y protección de fórmulas; xlsx con hojas Reporte+Criterios).
7. **`insights`/`assistant` sin estructura** → **PARCIAL**: `interpret` devuelve estructura aplicable; `explain` devuelve secciones; `assistant` conserva contrato.
8. **Stock bajo sin detalle** → **CORREGIDO** (`low_stock_variants` con variante/sucursal/talla/color/stock).
9. **Sin reservas en el dashboard** → **CORREGIDO** (`reservations_by_status`).
10. **`payment_method` con doble significado** → **DOCUMENTADO** (no se cambia el modelo); método real visible en `payment_methods`.
11. **Estado "expired"** fuera de `TRANSITIONS`: documentar, no transitable.

## 4. Plan de implementación (orden y verificación)

### A. Backend — métricas y contratos (esta tanda)
1. `ReportsService.dashboard`: agregar bloque **`meta`** (período aplicado,
   zona `America/La_Paz`, moneda, generado en, nota de cobertura) y métricas de
   período: `period.{orders,paid_orders,pending_orders,revenue,units_sold,
   ticket_avg,cancellation_rate}`; `units_sold`; `comparison` (anterior equivalente /
   misma fecha año previo con `%` o `null = Sin base comparable`); `low_stock_variants`
   (detalle por variante/sucursal); `reservations_by_status`; filtros `branch_id`,
   `category_id`, `status` y rango `date_from/date_to` aplicados a las métricas de
   período. **Compatibilidad hacia atrás**: conservar todas las claves previas y los
   parámetros `date_from/date_to`.
2. Arreglar `_window` naive/aware y limitar la carga (paginación opcional).
3. Corregir N+1 de `/commerce/admin/stock`.
4. `alembic/env.py`: importar `ReservationModel`.
5. Settings nuevos: `ai_timeout`, `ai_max_tokens`, `report_export_max_rows`
   (documentados, con valores de ejemplo vacíos para claves).

### B. Backend — endpoints nuevos (marcados como NUEVOS)
6. `POST /analytics/assistant/interpret` (permiso `dashboard.read`): consulta en
   lenguaje natural → `{ok, vista, filtros, agrupacion, metrica, comparacion,
   aclaraciones, respuesta}`. Resuelve nombres→ids desde catálogo real; si hay varias
   coincidencias pide selección. No ejecuta SQL libre; no toca datos.
7. `POST /analytics/assistant/explain` (permiso `dashboard.read`): dado el contexto de
   filtros actual, reobtiene métricas en el servidor y produce hallazgo/cifras/
   interpretación/acción/limitaciones. El servidor recalcula; no confía en el navegador.
8. `GET /analytics/reports/export?format=xlsx|csv` (permiso `dashboard.read`):
   exporta el conjunto filtrado autorizado (máx `report_export_max_rows`, filas y
   totales consistentes con el dashboard). XLSX con encabezados/fechas/importes y hoja
   "Criterios" (período, filtros, zona, moneda, generado el); CSV con metadatos en
   cabecera. Celdas de texto escapadas (nunca `=/-/+` inicial).
9. `POST /analytics/insights` mantiene firma (compat) pero acepta cuerpo opcional de
   filtros y SIEMPRE usa ese contexto; `POST /commerce/assistant` conserva su contrato.

### C. Verificación backend
- `pytest tests/unit/ventas_pagos/test_reports_service.py -q` (nuevos unit).
- `pytest tests/test_commerce_contract.py -q` (no romper el contrato).
- `pytest -q` completo del repo.

### D. Frontend (ver doc/ del frontend)
- Navegación diferenciada, contador de carrito real, robot SVG reutilizable,
  chat amplio (ampliar/minimizar, Enter/Shift+Enter, reintento sin duplicar,
  "Ver respuesta nueva", micrófono controlado, prefers-reduced-motion),
  módulo `ia-reportes` reestructurado por vistas con filtros/contexto de IA/
  exportación.

## 5. Métricas del dashboard (diccionario)

| Métrica | Definición | Fecha de referencia |
|---|---|---|
| Ingresos cobrados | Suma de `total` de pedidos con `payment_status=paid` | `created_at` (no existe fecha de pago; se documenta la limitación) — plan: agregar `paid_at` |
| Pedidos creados | Pedidos con `created_at` en el período | `created_at` |
| Ticket promedio | Ingresos cobrados / pedidos pagados del universo del período | `created_at` |
| Unidades vendidas | Suma de `item.quantity` de líneas de pedidos pagados del universo | `created_at` |
| Pedidos pendientes de pago | Pedidos `status=pending_payment` en el período | `created_at` |
| Stock bajo | Variantes con `quantity < umbral` por sucursal (fotografía; no histórico) | `now()` |

NO se muestran margen/rentabilidad/devolución/abandono/conversión (faltan costos o
eventos). No se suman monedas distintas: `commerce_currency` es única (bob). La zona
horaria de negocio es `America/La_Paz` (documentada en `meta.timezone`).

## 6. Pendientes que requieren nuevas tablas/eventos

- `orders.paid_at` (fecha de pago real) para "Ingresos cobrados" con referencia al pago.
- Evento de `cart` abandonado (abandono) y `refunds` (devoluciones) para esas métricas.
- `inventory_movements` (movimientos para stock histórico) — fuera del alcance actual.

## 7. Punto de reanudación (en este archivo al terminar la sesión)

- [x] A · Sección 4 completada
- [x] B · Sección 4 completada
- [x] C · Verificación aprobada (36 passed, 1 warning)

### Listo para continuar (sesión siguiente)
- Frontend contrato `Dashboard` ya consume `meta/period/comparison/low_stock_variants/
  reservations_by_status/payment_methods` y los tres endpoints nuevos (ver
  `frontend_marketplace_moda/doc/`).
- Pendiente de producto (no de backend): export **PDF**, `paid_at`, abandono de
  carrito, devoluciones, stock histórico (tablas/eventos nuevos).

---

## 8. Actualización 2026-09-16 — contexto visible en interpret (unidad 2-C)

**Estado: Verificado localmente** (`pytest -q` → 51 passed, 1 warning).

`ReportsAI.interpret(message, current, catalog)` ahora **usa `current`**
(antes lo ignoraba). Regla determinista: si el texto hace referencia explícita
al contexto visible (`esto|eso|ese/este contexto|lo que veo|en pantalla|de la
vista|visible|actual|esta ventana|de aqui`), siembra los filtros de `current`
(`branch_id`, `category_id`, `status`, rango `date_from/date_to`, col 2026) como
punto de partida y registra una aclaración ("Usé los filtros visibles del
dashboard como punto de partida."). Lo que el texto pide explícitamente después
(periodo, sucursal nombrada, categoría) gana sobre esa siembra. Pedidos sin
referencia al contexto (`"ventas por sucursal"`) no siembran nada: "por
sucursal" es agrupación, no filtro.

Pruebas nuevas: `tests/unit/ventas_pagos/test_reports_ai_contexto.py` (4 tests):
pedido referido siembra contexto; periodo explícito gana; sucursal nombrada gana;
sin referencia no siembra.