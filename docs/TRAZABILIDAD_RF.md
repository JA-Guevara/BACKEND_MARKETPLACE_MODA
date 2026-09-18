# Trazabilidad de requisitos funcionales

Dónde está implementado cada RF, en los tres proyectos. Sirve para revisar el alcance sin recorrer el código.

Leyenda: ✅ implementado · 🟡 parcial · ⛔ sin implementar · — no aplica.

| RF | Requisito | Backend | Web | Móvil |
|---|---|---|---|---|
| RF01 | Registrar clientes | ✅ `src/auth` | ✅ `/registrarse`, `/mi-cuenta` | 🟡 pantalla marcada |
| RF02 | Gestionar usuarios y roles | ✅ `src/usuarios`, `src/roles` | ✅ `/admin/users`, `/admin/roles` | — administración es web |
| RF03 | Gestionar ciudades y sucursales | ✅ `src/inventario_sucursales` | ✅ `/admin/cities`, `/admin/branches` | — |
| RF04 | Gestionar productos de ropa | ✅ `src/usuarios_catalogo` | ✅ `/admin/products` | — |
| RF05 | Tallas, colores, categorías y temporadas | ✅ `src/usuarios_catalogo` | ✅ datos maestros del catálogo | — |
| RF06 | Gestionar proveedores | ✅ `src/inventario_sucursales` | ✅ `/admin/suppliers` | — |
| RF07 | Consultar catálogo desde web **y móvil** | ✅ `/catalog/*` público | ✅ `/` y `/prendas/:slug` | 🟡 pantalla marcada |
| RF08 | Disponibilidad por sucursal | ✅ `commerce_stock` | ✅ ficha de prenda y reserva | 🟡 |
| RF09 | Varias prendas en una reserva | ✅ hasta 20 variantes | ✅ `/reservar` | 🟡 |
| RF10 | Registrar y gestionar reservas | ✅ `src/reservas` | ✅ cliente y `/admin/reservas` | 🟡 |
| RF11 | Notificar la reserva a la sucursal | ✅ correo HTML a `branches.notification_email`, más avisos internos de pedido y devolución | ✅ campo en el formulario de sucursal | — el aviso es del servidor |
| RF12 | Consultar estado de la reserva | ✅ listado, detalle e historial | ✅ `/mi-cuenta/reservas` | 🟡 |
| RF13 | Vestidor virtual en app móvil | ✅ `src/probador_virtual` | ✅ `/prendas/:slug/vestidor` | 🟡 pantalla marcada; ML Kit ya declarado |
| RF14 | Carrito de compras | ✅ carrito en servidor | ✅ `/carrito` | 🟡 |
| RF15 | Comprar por la web | ✅ pedidos y checkout | ✅ compra completa | — |
| RF16 | Comprar desde la app móvil | ✅ sin cambios necesarios | — | 🟡 pantalla marcada |
| RF17 | Ventas presenciales (cajero) | ✅ venta y devolución de mostrador | ✅ `/admin/caja`: escaneo, vuelto, comprobante y pestaña de devoluciones | — |
| RF18 | Pagos en punto de caja | ✅ efectivo, QR, tarjeta y transferencia, idempotente | ✅ selector de medio con su referencia propia | — |
| RF19 | Pasarela de pago | ✅ Stripe con webhook firmado y conciliación | ✅ checkout y retorno | 🟡 abre el navegador y concilia |
| RF20 | Descuento automático de inventario | ✅ al crear el pedido y al cobrar en caja | — efecto del servidor | — |
| RF21 | Existencias por sucursal | ✅ `commerce_stock` | ✅ `/admin/stock` | — |
| RF22 | Movimientos de inventario | ✅ kardex con saldo y actor | ✅ `/admin/stock` | — |
| RF23 | Temporadas y colecciones | ✅ `seasons`, `collections` | ✅ datos maestros | — |
| RF24 | Reportes de ventas e inventario | ✅ `/analytics/*` con exportaciones | ✅ `/admin/dashboard` | — |
| RF25 | Funcionalidad de IA | ✅ asistente, lectura de reportes y probador | ✅ asistente y vestidor | 🟡 vestidor pendiente |

## Casos de uso

| CU | Caso de uso | Estado |
|---|---|---|
| CU01–CU08 | Registro, sesión, usuarios y roles, catálogo, temporadas, proveedores, consulta pública, organización comercial | ✅ |
| CU09 | Consultar disponibilidad por sucursal | ✅ |
| CU10 | Armar una reserva con varias prendas | ✅ |
| CU11 | Registrar y gestionar reservas | ✅ |
| CU12 | Consultar estado de la reserva | ✅ |
| CU13 | Cancelar reserva | ✅ |
| CU14 | Atender reserva en sucursal | ✅ |
| CU15 | Notificar cambio de estado | ✅ correo en pedidos, reservas y devoluciones |
| CU16 | Utilizar el vestidor | ✅ web; 🟡 móvil |
| CU17 | Comprar desde la web | ✅ |
| CU18 | Cobrar en punto de caja | ✅ |
| CU19 | Registrar devolución | ✅ |

## Lo que falta

| Pendiente | Bloquea | Quién lo resuelve |
|---|---|---|
| Aplicar las migraciones `0011` y `0012` | Devoluciones (CU19) y correo de sucursal (RF11) | Ejecutar `alembic upgrade head` en la base compartida |
| Configurar SMTP y `OPERATIONS_EMAIL` | Que los correos de CU15 y RF11 salgan de verdad | Variables del servicio |
| Implementar las pantallas del móvil | RF07 móvil, RF13, RF16 | No requiere endpoints nuevos |
| Prueba punta a punta con datos reales | Confianza en la entrega | Una cuenta de cliente y una de administración |
| Probar el vestidor con cámara real | RF13 y RF25 | La lógica ya está cubierta por pruebas |

## Documentos relacionados

- `backend_marketplace_moda/docs/PROJECT_GUIDE.md`: arquitectura, modelo de datos, seguridad y reglas transaccionales.
- `backend_marketplace_moda/docs/API_CONTRACT.md`: contrato por endpoint, permisos y ejemplos.
- `frontend_marketplace_moda/docs/PROJECT_GUIDE.md`: arquitectura web, rutas y decisiones de interfaz.
- `mobile_marketplace_moda/docs/PROJECT_GUIDE.md`: arquitectura móvil, mapa de pantallas y orden de trabajo.
