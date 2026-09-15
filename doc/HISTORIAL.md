# Historial de avance

## 2026-09-15 — Verificación del contrato de probador virtual

- Revisados resolución de recurso activo, autenticación y registro del actor.
- 4 pruebas HTTP sobre SQLite descartable aprobadas; sin modificaciones de producción ni cambios a los contratos.
- PROBADOR_VIRTUAL.md documenta evidencia y límites. Frontend manual corregido; cámara física y seguimiento corporal pendientes.

## 2026-09-12 — Diagnóstico de petición del carrito

- Endpoints públicos/preflight publicados responden. Pendiente excepción del carrito con sesión real.
- Manejador de errores de base 503 con CORS y referencia de diagnóstico.
- 3 pruebas comerciales aprobadas; DIAGNOSTICO_RAILWAY.md agregado. Sin despliegue ni cambios a producción.

## 2026-09-12 — Contrato comercial y migración

- 2 pruebas comerciales aprobadas; incluye prenda desactivada visible para quitar pero rechazada al comprar.
- Generación SQL PostgreSQL aprobada. Cadena SQLite temporal no ejecutable por JSONB inicial; documentado, sin cambios a base real.
- COMERCIO.md registra cobertura y pendientes de concurrencia, migración real y Stripe externo.

## 2026-09-11 — Revisión de correo de auditoría

- Se confirmó que actor_email devuelve el correo del usuario relacionado con el evento; frontend lo prioriza en la tabla.
- No se modificó la captura del backend en esta sesión. Pendiente valorar una instantánea histórica para conservar correo tras eliminación/cambios de usuario.
- Pendientes de integración comercial y revisión general registrados en `../../frontend_marketplace_moda/doc/AJUSTES_VISUALES_Y_PENDIENTES.md`.

## 2026-09-11 — Galería en PATCH de prenda

- Agregado ImageEdit y campo images opcional en ProductUpdate.
- Se preservan IDs válidos y se rechazan IDs ajenos/repetidos; datos y relación se guardan juntos.
- Pruebas HTTP adicionales aprobadas junto con 118 comprobaciones de ciclo 1.
- Documento FORMULARIO_PRENDA_IMAGENES.md agregado. Sin migraciones ni cambios a la base real por esta mejora.

## 2026-09-10 — Validación ampliada de importación

- Prueba de lote con una fila válida y otra duplicada: no persistió la fila válida, tanto en preview como al intentar importar.
- Comprobados rechazo de digest de otro archivo y fórmulas Excel.
- Documentado CARGAS_MASIVAS.md con contratos, límites y cobertura pendiente.
- No se aplicaron migraciones ni se habilitaron cobros. El módulo comercial continúa pendiente de integración.

## 2026-09-10 — Recuperación y documentación

- Se inventariaron auditoría, Excel, imágenes y comercio escritos en disco.
- Se confirmó que el registro central de rutas aún no incorporaba Excel/imágenes/comercio y que no existía migración comercial 0003.
- Se guardaron decisiones y pendientes en `ESTADO_ACTUAL.md` para evitar pérdida de contexto.
- Pendiente validación conjunta y pruebas comerciales; no se han efectuado cobros reales.

## 2026-09-10 — Rutas e integración comprobadas

- Se registraron los routers `/api/v1/bulk` y `/api/v1/media` en `src/config/routes.py`.
- Se confirmó por importación de la aplicación que las rutas están disponibles.
- Pruebas unitarias de bitácora: 3 aprobadas. Advertencia de permisos al escribir la caché de pytest; no afectó las pruebas.
- Contrato del ciclo 1: 118 comprobaciones HTTP aprobadas usando base descartable.
- Prueba adicional `../frontend_marketplace_moda/scripts/test_excel_media.py` aprobada: descarga de plantillas/exportaciones, restricción por permisos, rollback de preview, importación de talla, duplicados, imagen válida/lectura pública e imagen falsa rechazada.
- Comercio permanece sin registrar: completar migración y validación antes de habilitarlo sobre datos persistentes.
