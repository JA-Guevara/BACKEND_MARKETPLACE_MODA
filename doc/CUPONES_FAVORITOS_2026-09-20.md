# Cupones, promociones y favoritos

## Estado: implementado localmente — requiere migración 0015 al desplegar

El módulo agrega dos capacidades comerciales sin permitir que el navegador
modifique importes ni condiciones.

## Cupones y promociones

Una misma campaña puede ser automática o requerir código:

- **Con código:** el cliente lo escribe en el carrito, por ejemplo `VERANO15`.
- **Sin código:** se aplica automáticamente la mejor campaña vigente que
  corresponda al carrito.
- Los tipos disponibles son porcentaje, importe fijo y envío gratis.
- Puede limitarse por fechas, stock de usos global, usos por cliente, importe
  mínimo, categoría, prenda o clientes frecuentes (mínimo de compras pagadas).
- Por diseño se aplica una campaña automática y, si es válido, un cupón. Dos
  campañas automáticas no se acumulan.
- El pedido persiste subtotal, descuento, campañas aplicadas y código. Al
  confirmarlo el servidor vuelve a validar vigencia y límites con bloqueo y
  registra cada uso de forma única.

`Envío gratis` queda visible como beneficio comercial. FashionStore todavía no
modela un costo de envío separado, por lo que no inventa un descuento monetario.

## Favoritos y alertas

El cliente puede guardar una prenda desde su ficha y gestionar sus alertas en
**Mi cuenta > Mis favoritos**:

- alerta de reposición cuando una variante pasa de cero a unidades disponibles;
- alerta de rebaja cuando el precio base baja respecto al precio observado al
  guardar la prenda;
- ambos avisos se mandan al correo de su cuenta por el SMTP ya configurado y se
  registran en bitácora; se puede desactivar cada aviso o quitar el favorito.

## Operación

Administración abre **Gestión > Cupones y promociones**, crea la campaña y la
puede pausar sin borrarla. Los campos de categoría y prenda se eligen desde el
catálogo actual. El cliente ingresa el cupón en el carrito; cualquier condición
incorrecta retorna un mensaje y no altera el total.

## Despliegue

1. Desplegar backend con la migración `20260920_0015`.
2. Ejecutar `alembic upgrade head` contra la base de producción.
3. Desplegar el frontend en el mismo ciclo.
4. Crear una campaña de prueba de importe fijo, agregar una prenda al carrito,
   verificar subtotal/descuento/total y confirmar que el pedido conserva el
   beneficio.
5. Guardar una prenda sin stock, ingresar unidades desde administración y
   confirmar el correo y el evento de bitácora.

## Pendiente deliberado

No hay motor de tarifas de envío. Cuando exista, `free_shipping` deberá reducir
la línea de flete real y no solo mostrarse como beneficio.
