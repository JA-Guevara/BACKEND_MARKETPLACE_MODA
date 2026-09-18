# FashionStore Backend — guía del proyecto

## 1. Propósito y alcance actual

FashionStore es el backend de una plataforma de comercio electrónico de ropa con catálogo público como página principal. El acceso no comienza en una pantalla de login: cualquier visitante puede consultar productos, categorías, tallas, colores, temporadas, colecciones y sucursales. La autenticación se solicita cuando una operación es personal o administrativa.

El **ciclo I** de la documentación funcional quedó así:

| Caso de uso | Cobertura en el backend |
|---|---|
| CU01 Registrar cliente | Registro, política de contraseña, rol `client`, verificación de correo y bitácora |
| CU02 Iniciar sesión | JWT de acceso, refresh rotatorio, logout, bloqueo por intentos, recuperación y cambio de contraseña |
| CU03 Gestionar usuarios y roles | CRUD, activación, desactivación, desbloqueo, borrado lógico, restauración, roles y permisos |
| CU04 Gestionar catálogo de prendas | Productos, categorías, tallas, colores, variantes, imágenes, precios, marca y recurso AR |
| CU05 Gestionar temporadas y colecciones | CRUD completo, estado activo/inactivo y asociaciones con productos |
| CU06 Gestionar proveedores | CRUD, búsqueda, estado, borrado lógico y vínculo proveedor-producto |
| CU07 Consultar catálogo | Rutas públicas, detalle por `slug`, paginación y filtros combinables |
| CU08 Gestionar ciudades, sucursales y cajas | CRUD, estados, borrado lógico, ubicación, horarios y cajas por sucursal |

Del ciclo II quedan implementados:

| Caso de uso | Cobertura en el backend |
|---|---|
| CU09 Consultar disponibilidad por sucursal | Existencias por variante y sucursal, con consulta previa antes de reservar |
| CU10 Armar una reserva con varias prendas | Hasta 20 variantes distintas por reserva, agrupando repetidas (RF09) |
| CU11 Registrar y gestionar reservas | Alta idempotente, apartado de unidades, estados y cancelación |
| CU12 Consultar estado de la reserva | Listado propio, detalle e historial de cambios |
| CU13 Cancelar reserva | Cancelación del cliente con devolución de las unidades apartadas |
| CU14 Atender reserva en sucursal | Confirmar, preparar y registrar la visita atendida |
| CU15 Notificar cambio de estado | Correo al cliente en pedidos, reservas y devoluciones; aviso a la sucursal (RF11) |
| CU16 Utilizar el vestidor virtual | Preparación del recurso por producto y color, anclajes y sesión de prueba |
| CU17 Comprar desde la web | Carrito en servidor, pedido con apartado de existencias y dirección de entrega |
| CU18 Cobrar en punto de caja | Venta presencial idempotente, con precios y totales calculados por el servidor |
| CU19 Registrar devolución | Solicitud del cliente, resolución administrativa y reingreso al inventario |

También están operativos el pago con Stripe y su conciliación, el kardex de movimientos, el tablero de reportes con exportaciones y el asistente de IA.

Un diseño inicial había dejado ocho carpetas de módulo vacías (`compras`, `dashboard`, `envios`, `pagos`, `pedidos`, `productos`, `resenas`, `tiendas`) cuya función terminó viviendo en los módulos grandes. Se eliminaron junto con los envoltorios que nadie usaba: `src/` pasó de 254 a 109 archivos sin cambiar una sola ruta.

## 2. Organización del código

El código sigue una separación por responsabilidades:

- `domain`: reglas y conceptos del negocio que no dependen de HTTP.
- `application`: servicios y casos de uso; aquí se coordinan validaciones, persistencia y bitácora.
- `infrastructure`: modelos SQLAlchemy, repositorios, seguridad, correo y base de datos.
- `web`: rutas FastAPI y esquemas Pydantic de entrada/salida.

Los límites funcionales activos son:

- `src/auth`: registro, sesiones, tokens, correo y contraseñas.
- `src/usuarios_catalogo`: punto de entrada consolidado para usuarios, roles, permisos y catálogo.
- `src/inventario_sucursales`: ciudades, sucursales, puntos de caja y proveedores; será el límite natural para existencias y movimientos.
- `src/bitacora`: registro y consulta inmutable de eventos.
- `src/ventas_pagos`: carrito, pedidos, pagos con Stripe, venta en caja, existencias, movimientos, devoluciones y reportes. Es el módulo más grande del proyecto.
- `src/reservas`: agenda de visitas para probarse tallas, con apartado de unidades.
- `src/probador_virtual`: preparación del recurso de la prenda, anclajes y sesión de prueba.
- `src/notificaciones`: avisos por correo de pedidos, reservas y devoluciones.
- `src/shared`: respuestas, paginación y excepciones comunes.
- `src/config/routes.py`: composición única de rutas del API.

`src/usuarios` y `src/roles` continúan como componentes internos ya estables y se exponen desde `usuarios_catalogo`. Esto conserva compatibilidad sin duplicar lógica.

## 3. Modelo de datos

### Seguridad y clientes

- `users`: credenciales, perfil, verificación, estado, intentos fallidos, bloqueo y borrado lógico.
- `user_addresses`: direcciones de entrega del cliente.
- `roles`, `permissions`, `user_roles`, `role_permissions`: control de acceso RBAC.
- `refresh_tokens`: sesiones renovables; el token completo nunca se guarda, sólo su hash.
- `password_reset_tokens`, `email_verification_tokens`: tokens opacos de un solo uso y con vencimiento.
- `audit_events`: bitácora de autenticación y operaciones administrativas.

### Catálogo

- `categories`: categorías jerárquicas mediante `parent_id`.
- `sizes`: tallas ordenables.
- `colors`: colores con código hexadecimal.
- `seasons`: temporadas y rango de fechas opcional.
- `collections`: colecciones, opcionalmente asociadas a una temporada.
- `products`: información comercial, precio base, publicación y asociaciones principales.
- `product_variants`: combinación única talla/color, SKU, código de barras y precio alternativo.
- `product_images`: imágenes ordenadas y una posible imagen principal.
- `ar_assets`: recursos para futura visualización AR (`image_overlay`, `glb`, `gltf`, `usdz`).
- `product_suppliers`: relación producto-proveedor, SKU del proveedor, costo y proveedor principal.

### Organización comercial

- `cities`: ciudad, departamento y país.
- `branches`: sucursal, ciudad, dirección, coordenadas y horarios en JSON.
- `cash_points`: puntos de caja pertenecientes a una sucursal.
- `suppliers`: datos fiscales y de contacto del proveedor.

`branches.notification_email` es la casilla que recibe los avisos de reserva de esa sucursal (RF11). Si está vacía, el aviso va a `OPERATIONS_EMAIL`.

### Comercio, existencias y devoluciones

- `commerce_stock`: unidades por variante y sucursal. Es la **única** fuente de existencias: reservas, pedidos web y caja consultan y modifican esta tabla.
- `commerce_stock_movements`: kardex. Cada cambio deja saldo anterior, saldo posterior, motivo, referencia y actor. Dos restricciones de base impiden saldos negativos y movimientos descuadrados.
- `commerce_cart_items`: carrito del cliente, en el servidor.
- `commerce_orders`: pedidos web y ventas de caja en la misma tabla, distinguidas por `sales_channel`. Guardan copia de las prendas y de la dirección, más el historial `tracking`.
- `commerce_order_returns`: devoluciones (CU19), con copia del detalle y el importe a reintegrar.
- `commerce_webhook_events`: eventos de Stripe ya procesados, para descartar reintentos.

### Reservas y probador

- `reservations`: visita agendada, sucursal, horario, prendas apartadas e historial de estados. `inventory_held` distingue las reservas anteriores a la migración de inventario, que no apartaron nada.
- `virtual_tryon_assets`: recurso preparado del probador, único por producto y color.

Las eliminaciones de usuarios, productos, proveedores, sucursales y cajas son lógicas. Los catálogos maestros y ciudades sólo se eliminan físicamente cuando no tienen asociaciones. Esto evita perder historial o romper referencias.

## 4. Seguridad implementada

- Contraseñas con Argon2 y mínimo de 12 caracteres.
- Exigencia de mayúscula, minúscula, número y carácter especial.
- Rechazo de contraseñas que contienen el nombre local del correo.
- JWT de acceso de corta duración.
- Refresh token rotatorio; su reutilización revoca las sesiones del usuario.
- Tokens de recuperación y verificación aleatorios, guardados como SHA-256.
- Bloqueo temporal después del número configurable de intentos fallidos.
- Revocación de sesiones al cambiar o restablecer la contraseña.
- Mensajes neutros en recuperación y reenvío de verificación para no revelar si un correo existe.
- Autorización por permisos, no por nombres de rol codificados en las rutas.
- Registro de actor, acción, entidad, IP, agente de usuario, metadatos y fecha en bitácora.

La bitácora no ofrece operaciones de edición ni eliminación.

## 5. Roles y permisos iniciales

La primera migración crea los roles:

- `superadmin`
- `admin`
- `store_manager`
- `cashier`
- `client`

También crea los permisos base `users.read`, `users.write`, `roles.read`, `roles.write` y `audit.read`. La migración del ciclo I agrega:

- `catalog.read`, `catalog.write`
- `suppliers.read`, `suppliers.write`
- `branches.read`, `branches.write`

`superadmin` y `admin` reciben todos esos permisos durante las migraciones. Los demás roles quedan deliberadamente sin permisos administrativos hasta que el administrador defina la matriz exacta del negocio mediante el API de roles.

## 6. Configuración local

Requisitos: Python 3.12 y PostgreSQL 15 o superior.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

El archivo `.env` se crea a mano en la raíz del backend; no se versiona y no hay plantilla en el
repositorio para no arrastrar valores de ejemplo a producción.

Variables importantes:

| Variable | Uso |
|---|---|
| `DATABASE_URL` | Conexión SQLAlchemy a PostgreSQL |
| `JWT_SECRET_KEY` | Firma de tokens; debe ser larga, aleatoria y privada |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del access token |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Duración máxima de la sesión renovable |
| `MAX_LOGIN_ATTEMPTS` | Intentos fallidos antes del bloqueo |
| `ACCOUNT_LOCK_MINUTES` | Duración del bloqueo temporal |
| `FRONTEND_URL` | Base de los enlaces enviados por correo |
| `CORS_ORIGINS` | Orígenes web autorizados |
| `SMTP_*` | Servidor de correo para verificación, recuperación y avisos de estado |
| `OPERATIONS_EMAIL` | Casilla que recibe los avisos de reserva cuando la sucursal no tiene correo propio (RF11) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Pasarela de pago y verificación de la firma del webhook |
| `COMMERCE_CURRENCY` | Moneda de los pedidos |
| `MEDIA_PUBLIC_BASE_URL` | Base **absoluta** de las imágenes servidas. Tiene que ser una dirección alcanzable desde el cliente: con `localhost` las fotos no cargan en un emulador ni en un teléfono |
| `AI_API_KEY`, `AI_MODEL` | Asistente y lectura de reportes |

Si SMTP no está configurado, el usuario se registra y las operaciones se completan, pero no sale ningún correo: el envío es "lo mejor posible" y su resultado queda en bitácora. En producción deben configurarse SMTP, HTTPS, una clave JWT real y orígenes CORS exactos.

Ninguna credencial va en el código ni en el repositorio. Si una clave se expuso alguna vez en un chat, un log o una captura, hay que rotarla.

## 7. Migraciones y primer arranque

Alembic tiene una cadena lineal:

1. `20260903_0001`: autenticación, usuarios, roles, permisos, direcciones y bitácora.
2. `20260905_0002`: catálogo, proveedores, ciudades, sucursales, cajas y nuevos permisos.
3. `20260910_0003`: existencias, carrito, pedidos y eventos de Stripe.
4. `20260912_0004`: código postal y país en las direcciones del cliente.
5. `20260912_0005`: reservas de probador.
6. `20260916_0006`: clave idempotente de reservas.
7. `20260916_0007`: fecha de acreditación del pago.
8. `20260917_0008`: venta en caja y kardex de movimientos.
9. `20260917_0009`: apartado de inventario en reservas.
10. `20260917_0010`: recursos preparados del probador virtual.
11. `20260918_0011`: correo de aviso de la sucursal (RF11).
12. `20260918_0012`: devoluciones de pedidos (CU19).

Todas las migraciones son aditivas y reversibles. Las dos últimas todavía no están aplicadas en la base compartida: hasta correr `alembic upgrade head`, las rutas de devolución responden error.

Aplicar todo:

```powershell
.venv\Scripts\alembic.exe upgrade head
```

Consultar el estado:

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe heads
```

**Primer administrador.** No hay un script para crearlo: se inserta la fila en `users` con la
contraseña ya cifrada —el backend usa el mismo algoritmo que en el registro— y se la asocia al rol
`superadmin` en `user_roles`. Conviene hacerlo una sola vez y con una contraseña real, nunca una de
ejemplo.

## 8. Ejecución y documentación interactiva

```powershell
.venv\Scripts\uvicorn.exe src.main:app --reload --port 8000
```

- API base: `http://localhost:8000/api/v1`
- Swagger UI: `http://localhost:8000/docs`
- Esquema OpenAPI: `http://localhost:8000/openapi.json`
- Salud: `http://localhost:8000/health`

Las rutas públicas del catálogo no llevan token. Las rutas protegidas reciben:

```http
Authorization: Bearer <access_token>
```

## 9. Flujo recomendado para el frontend

1. La portada consulta `/catalog/products` y los datos maestros públicos.
2. Los filtros se mantienen en la URL del frontend y se traducen directamente a parámetros del API.
3. Login guarda el access token sólo en memoria cuando sea posible y usa el refresh token mediante un almacenamiento protegido.
4. Ante un `401`, el cliente intenta una sola renovación en `/auth/refresh`; si falla, cierra la sesión local.
5. Los menús administrativos se habilitan usando los permisos incluidos en `data.user.roles[].permissions`.
6. Después de crear o editar un registro, el frontend utiliza el objeto retornado y no necesita una segunda consulta.
7. Una eliminación lógica desaparece del listado normal; para administración puede recuperarse usando `include_deleted=true` y la operación de activación/restauración correspondiente.

El contrato exacto, ejemplos de objetos y tabla de endpoints están en `docs/API_CONTRACT.md`.

## 10. Reglas transaccionales destacadas

- Crear un producto valida primero todas sus referencias, duplicados de SKU/código de barras y banderas principales.
- Sólo puede existir una imagen principal y un proveedor principal por producto.
- Una combinación talla/color no puede repetirse dentro del mismo producto.
- Un producto público debe estar activo y no eliminado; sus variantes y recursos AR inactivos se ocultan.
- El costo del proveedor nunca aparece en la respuesta pública.
- No se puede desactivar o eliminar un dato maestro mientras esté siendo usado.
- Al desactivar o eliminar una sucursal se desactivan sus cajas.
- No se puede activar una caja si su sucursal está inactiva.
- No se puede eliminar una ciudad con sucursales asociadas.
- Crear un pedido o una reserva **aparta** las unidades en el acto; si falla una sola prenda se revierte la operación entera. Nunca queda un apartado a medias.
- Cancelar o vencer un pedido, y cancelar o atender una reserva, devuelven exactamente las unidades que se habían apartado.
- Las ventas de caja y las reservas usan una clave idempotente: reintentar con los mismos datos devuelve lo ya registrado; con datos distintos responde `409`.
- Un pago se acredita una sola vez: el webhook de Stripe y la conciliación por consulta comparten la misma transición y descartan eventos repetidos.
- Una devolución aprobada **no** devuelve stock; las unidades reingresan al cerrarla, que es cuando las prendas volvieron físicamente.
- Un aviso por correo nunca revierte la operación que lo originó: se envía después de confirmar y su resultado queda en bitácora.

## 11. Pruebas y control antes de entregar

Pruebas locales sin la verificación de red:

```powershell
.venv\Scripts\python.exe -B -m pytest -q --ignore=tests/integration/database/test_connection.py -p no:cacheprovider
```

Prueba completa, incluida la base configurada en `.env`:

```powershell
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

La prueba de conexión externa requiere acceso de red y una `DATABASE_URL` válida. No se deben imprimir ni adjuntar archivos `.env`, tokens o contraseñas en reportes.

## 12. Qué falta para cerrar el alcance

1. **Aplicar las migraciones `0011` y `0012`** en la base compartida.
2. **Configurar SMTP real** (`SMTP_HOST` y siguientes, más `OPERATIONS_EMAIL`). Sin eso no sale ningún correo, y tampoco falla nada.
3. **App móvil Flutter** (`mobile_marketplace_moda`): es lo único con RF sin cumplir —RF07 móvil, RF13 y RF16—. No requiere endpoints nuevos; el detalle está en la guía de ese proyecto.
4. **Prueba punta a punta** contra la base real, con una cuenta de cliente y una de administración.
5. Opcional: notificaciones push, que sí exigirían backend nuevo (registro de dispositivos y envío). Ningún RF lo pide.
