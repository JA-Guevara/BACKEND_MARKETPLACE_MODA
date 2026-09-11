# Historial de avance

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
