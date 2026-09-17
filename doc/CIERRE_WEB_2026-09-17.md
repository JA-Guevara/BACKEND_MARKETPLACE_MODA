# Cierre funcional web — 17 de septiembre de 2026

## Alcance implementado

La aplicación web cubre los procesos del enunciado: acceso y roles, catálogo y sus variantes, proveedores y sucursales, carga/exportación masiva, carrito, pedido y cobro con Stripe, seguimiento, reservas de varias prendas, administración de reservas, inventario por sucursal, pagos, bitácora con correo del actor, dashboard, exportaciones múltiples y asistente de IA.

También queda integrado el probador web con cámara y recurso AR de cada prenda. Es una superposición 2D guiada por pose; no pretende generar un cuerpo o modelo 3D nuevo. Flutter sigue siendo el único cliente pendiente por desarrollar.

## Cierre de inventario y caja

Las migraciones `20260917_0008` y `20260917_0009` agregan:

- venta presencial en un punto de caja activo, con precio calculado por el servidor, comprobante PDF y una clave de reintento que impide duplicar cobros;
- libro de movimientos por sucursal y variante: saldo anterior/final, diferencia, motivo, referencia y correo del actor;
- apartados reales para reservas nuevas. Al cancelar o atender una reserva se liberan exactamente sus unidades. Las reservas históricas no se alteran ni liberan unidades que nunca apartaron;
- pedidos web, caja y reservas usan el mismo bloqueo de existencias y la misma bitácora de stock.

La interfaz incorpora **Administración → Caja** y el historial de movimientos dentro de **Existencias**. Un usuario de caja necesita `commerce.write`; el ajuste e ingreso/salida de stock requiere `stock.write`.

## Validación realizada

- Backend: `105 passed` con `PYTHONPATH=.`. Incluye regresiones de Stripe, reportes, asistente, catálogo, reserva apartada/liberada y venta presencial idempotente.
- Frontend: `175 passed` mediante `npm run test:ci`.
- Frontend: `npm run build` correcto. Persiste un aviso de presupuesto CSS preexistente del dashboard, sin error de compilación.
- Alembic: `upgrade head --sql` generado correctamente para toda la cadena hasta `20260917_0009`; esta comprobación no modifica ninguna base de datos.

## Publicación pendiente, paso único de infraestructura

Antes de usar Caja, movimientos y apartados de reservas en Railway se debe publicar este código y ejecutar una sola vez:

```powershell
alembic upgrade head
```

Después corresponde una verificación breve en el servidor: crear una reserva de una unidad, confirmar que baja el stock, cancelarla y confirmar que vuelve; registrar una venta de caja y descargar su comprobante. Stripe e IA deben probarse con las claves ya configuradas en ese servidor, sin exponerlas en el repositorio.

No se ejecutó la migración contra Railway desde esta estación para no cambiar datos de producción sin una publicación controlada.
