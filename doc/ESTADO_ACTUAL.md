# Estado y punto de reanudación

Actualizado: 10 de septiembre de 2026. Trabajo en curso; presencia de archivos no significa validación funcional.

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
