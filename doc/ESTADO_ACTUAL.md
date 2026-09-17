# Estado y punto de reanudación

Actualización 17/09 — Dashboard frontend reorganizado en tres vistas; contrato backend sin cambios. Generación IA/3D del probador sigue como propuesta, no implementada. Coordinación y alcance en [dashboard y probador](DASHBOARD_Y_PROBADOR_2026-09-17.md).

Actualización 17/09 — Conciliación autenticada de Stripe y confirmación compartida con webhook; validación de importe/moneda/pedido y protección frente a repeticiones. **84 pruebas unitarias aprobadas**, incluidas 12 nuevas de pagos. Frontend asociado: 161 pruebas y build aprobados. Sin despliegue ni modificación de pedidos publicados. Ver [contrato y pendientes de servidor](STRIPE_Y_ASISTENTE_2026-09-17.md).

Actualización 15/09 — Contrato de probador verificado con 4 pruebas HTTP aisladas. PROBADOR_VIRTUAL.md identifica rutas, actor en bitácora y límites. Sin cámara física ni cambios a producción; seguimiento corporal pendiente. Las notas siguientes conservan sus fechas históricas.

Estado vigente 12/09: interfaces comerciales conectadas y 2 pruebas de contrato aprobadas. Generación SQL PostgreSQL aprobada; pendiente ejecución de migración en PostgreSQL descartable, concurrencia y Stripe externo. Consultar COMERCIO.md; las notas del 10/09 describen el inventario inicial.

Actualizado: 10 de septiembre de 2026. Trabajo en curso; presencia de archivos no significa validación funcional.

Actualización 11/09: galería integrada en crear/editar prenda y guardado conjunto probado (ver FORMULARIO_PRENDA_IMAGENES.md). Comercio y analítica ya aparecen registrados en routes.py y existe migración 0003, pero el agente se interrumpió por créditos antes de completar la entrega y su validación. No aplicar automáticamente la migración ni declarar pagos listos.

## Solicitud y arquitectura

Mantener FastAPI y las capas de cada funcionalidad. El usuario amplió el ciclo 1 del documento FashionStore con importación Excel, bitácora detallada, imágenes, métricas/IA, carrito, pedidos, Stripe y seguimiento. La trazabilidad general y el orden de pantallas están en `../../frontend_marketplace_moda/doc/ESTADO_ACTUAL.md`.

## Inventario de trabajo

| Módulo | Código existente | Pendiente indispensable |
| --- | --- | --- |
| Auditoría | Contexto de solicitud, actor y presentación; `BITACORA.md` | Reejecutar pruebas y comprobar atribución de eventos |
| Excel | Router integrado; plantillas/exportación y preview/importación de talla probados | Ampliar casos de referencias y atomicidad con varias filas |
| Imágenes | Router integrado; carga, lectura pública, permisos y contenido inválido probados | Prueba visual y política de limpieza de archivos no asociados |
| Comercio | `src/ventas_pagos` con modelos, servicio, gateways y rutas | Migración 0003, permisos, pruebas de stock, propiedad del pedido e idempotencia |
| Analítica | Rutas dashboard/insights en ventas_pagos | Conectar frontend y verificar métricas |
| Configuración | Campos Stripe, IA y almacenamiento escritos | Verificar dependencias y `.env.example`; no documentar secretos |

## Decisiones

- Excel prioritario para prendas/variantes, proveedores y maestros. No importar credenciales ni confirmar pagos por Excel. Validar y previsualizar antes de confirmar.
- Actor legible: nombre/correo del usuario autenticado; UUID disponible en detalle. No confiar indiscriminadamente en cabeceras de IP de proxies.
- Imágenes: validar contenido y dimensiones, convertir a WebP, generar nombre propio. Pendiente política de limpieza de imágenes no asociadas y almacenamiento de producción.
- Pagos: precios y stock calculados en servidor; Stripe de prueba requiere claves y webhook. Una redirección de éxito no constituye evidencia de pago.
- IA opcional con métricas agregadas. Ausencia de clave debe indicarse sin inventar recomendaciones provenientes de un servicio externo.

## Reanudación segura

Revisar archivos existentes antes de continuar: las tareas previas dejaron implementaciones parciales y actualmente no hay agentes activos. Completar migración antes de habilitar comercio sobre una base persistente. Ejecutar primero pruebas aisladas; no modificar la base del usuario para simular pagos. Registrar resultados reales en HISTORIAL.md.
