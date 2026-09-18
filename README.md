# FashionStore API

Backend para la plataforma de comercio electronico de ropa. El ciclo I implementa autenticacion, usuarios, roles, permisos, bitacora, catalogo publico y administrativo, proveedores, ciudades, sucursales y puntos de caja.

## Funcionalidades disponibles

- Registro, login, logout y consulta del usuario autenticado.
- JWT de acceso y refresh token rotatorio almacenado como hash.
- Bloqueo temporal configurable por intentos fallidos.
- Recuperacion y cambio de contrasena.
- Verificacion y reenvio de verificacion de correo.
- CRUD administrativo de usuarios con activacion, desactivacion, desbloqueo, borrado logico y restauracion.
- Gestion de direcciones del cliente.
- CRUD de roles y permisos, con proteccion de roles del sistema.
- Bitacora inmutable con filtros y paginacion.
- Migracion inicial con roles y permisos base.
- Catalogo publico con productos, variantes, imagenes, filtros y detalle por slug.
- Gestion completa de categorias, tallas, colores, temporadas y colecciones.
- Gestion de proveedores y su relacion con productos.
- Gestion de ciudades, sucursales y puntos de caja.

El catalogo sera publico. El inicio de sesion se exigira solamente en operaciones personales o protegidas, como carrito, reservas, compras y administracion.

## Preparacion local

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Cree un archivo `.env` en la raiz del backend con `DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`,
`FRONTEND_URL`, las variables `SMTP_*`, `OPERATIONS_EMAIL` y las claves de Stripe. La lista completa
esta en `docs/PROJECT_GUIDE.md`, seccion 6. El `.env` no se versiona y no debe contener credenciales
de ejemplo en un entorno real.

## Migraciones

Aplicar las migraciones:

```powershell
alembic upgrade head
```

El primer administrador se crea directamente en la base: inserte una fila en `users` con la
contrasena ya cifrada y asociela al rol `superadmin` en `user_roles`. No existe un script para esto.

## Ejecucion

```powershell
uvicorn src.main:app --reload --port 8000
```

Documentacion interactiva: `http://localhost:8000/docs`.

## Reservas para probarse tallas

Una visita se agenda para probarse una talla concreta, así que el sistema verifica que la sucursal
elegida realmente la tenga.

- `GET /reservations/availability?branch_id=&variant_ids=` responde, por cada variante pedida, si
  está disponible, cuántas unidades hay y el motivo cuando no (sin unidades o prenda despublicada).
  Se declara antes que `/{reservation_id}` para que la ruta con parámetro no capture la palabra
  `availability`.
- `CrearReserva` valida esa disponibilidad antes de registrar: si falta alguna talla devuelve 422
  nombrando prenda y talla, en lugar de aceptar la visita y hacer viajar al cliente al local.
- El frontend consulta la disponibilidad al elegir sucursal, la muestra por fila y bloquea el envío
  mientras haya tallas faltantes.

Pruebas en `tests/test_reservations_availability.py`. Nota para escribir pruebas nuevas: la base de
QA es compartida por toda la suite y otras pruebas dejan el producto de ejemplo eliminado, así que
cada caso debe crear sus propios datos en lugar de asumir el catálogo sembrado.

## Avisos por correo (CU15 y RF11)

Cada cambio de estado que le importa al cliente sale por correo: pedido creado, pago confirmado,
preparación, envío, entrega, cancelación y vencimiento; y en reservas, registro, confirmación,
prendas listas, visita atendida y cancelación. Las devoluciones avisan en cada paso.

Los avisos no son solo de cara al cliente. La sucursal recibe el **pedido web por preparar** —las
prendas ya quedaron apartadas del stock, así que la demora en verlo es demora real— y gestión recibe
la **devolución por revisar**, que mientras espera inmoviliza unidades. Una devolución atendida en
caja no genera ese aviso: ya quedó resuelta.

Al registrarse una reserva también se avisa a la sucursal (RF11). El destinatario es el campo
`notification_email` de la sucursal; si está vacío, el aviso va a `OPERATIONS_EMAIL`.

Cada aviso sale en **dos versiones**: HTML con el diseño de la tienda y texto plano para los clientes
que bloquean HTML. El marco visual está en `src/notificaciones/domain/diseno.py` y el contenido de
cada situación en `plantillas.py`; ambos son funciones puras y se verifican sin servidor de correo.

Una venta cobrada en caja no informa un estado: el cliente ya se llevó la prenda, así que recibe el
**comprobante** con el detalle, la forma de pago y la referencia del cobro.

El envío es "lo mejor posible": si el servidor de correo está caído o sin configurar, la operación
igual se registra y en bitácora queda `notificaciones.email_enviado` o `notificaciones.email_fallido`
con el destinatario. Sin `SMTP_HOST` no se envía nada y nada falla, que es el modo de desarrollo.

Variables de entorno:

```
SMTP_HOST=smtp.tu-proveedor.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=no-reply@tu-dominio.com
SMTP_USE_TLS=true
OPERATIONS_EMAIL=operaciones@tu-dominio.com
```

Las credenciales van en el `.env` o en las variables del servicio, nunca en el código.

## Punto de venta (RF17, RF18)

`POST /commerce/admin/pos/sales` registra una venta ya cobrada. La clave `client_request_id` la hace
idempotente: reintentar con los mismos datos devuelve la venta registrada en vez de cobrar dos veces.
Los precios, los totales y la disponibilidad los toma el servidor del catálogo, nunca del cliente.

Para atender una devolución en el mostrador:

- `GET /commerce/admin/pos/orders?number=FS-...`: busca la venta y devuelve qué queda por devolver.
- `POST /commerce/admin/pos/returns`: registra la devolución **ya cerrada** y reintegra.

En el mostrador el circuito de tres pasos del canal web no aplica: el cliente entrega la prenda y
cobra en el momento, así que la devolución nace en `completed` y las unidades vuelven al stock
enseguida, con movimiento `return_received`.

## Devoluciones (CU19)

Se puede devolver un pedido entregado y pagado dentro de los 15 días desde la entrega, y solo las
unidades que todavía no estén en otra devolución vigente.

- `POST /commerce/orders/{id}/returns`: el cliente solicita la devolución (prendas y motivo).
- `GET /commerce/orders/{id}/returns`: qué puede devolver y qué devoluciones ya tiene.
- `GET /commerce/returns`: sus devoluciones.
- `GET /commerce/admin/returns`: bandeja de administración (`commerce.read`).
- `PATCH /commerce/admin/returns/{id}`: aprobar, rechazar o cerrar (`commerce.write`).

El circuito es `requested → approved → completed`, con rechazo posible en los dos primeros pasos.
**Aprobar no devuelve stock**: las unidades vuelven a la sucursal recién al pasar a `completed`, que
es cuando las prendas están físicamente de nuevo en el local, y se registran como movimiento de
inventario `return_received`. Un rechazo libera las unidades para que el cliente pueda volver a
pedirlas.

## Catálogo de demostración

`scripts/seed_demo_catalog.py` carga ochenta prendas (diez por tipo: poleras, camisas, blusas,
pantalones, vestidos, chaquetas, faldas y shorts) con imagen, cuatro variantes de talla y existencias
en cada sucursal activa. Escribe en la base configurada en `.env`.

```powershell
.venv\Scripts\python.exe scripts\seed_demo_catalog.py
```

- **Imágenes.** `scripts/demo_images.py` las dibuja con Pillow según el tipo de prenda y su color; no
  descarga nada. Se guardan en `frontend_marketplace_moda/public/demo/` (unos 8 KB cada una) y se
  referencian con ruta relativa (`/demo/archivo.webp`), de modo que se ven tanto en el entorno local
  como en el desplegado. Nota: esa ruta relativa no es una URL absoluta, así que un cliente externo
  que consuma la API (por ejemplo la app móvil) debe anteponer el origen del frontend.
- **Reversión.** Todo lo creado queda anotado en `scripts/demo_catalog_manifest.json`. Para deshacer:

  ```powershell
  .venv\Scripts\python.exe scripts\cleanup_demo_catalog.py            # simulación
  .venv\Scripts\python.exe scripts\cleanup_demo_catalog.py --aplicar  # borra
  ```

  Borra solo esos identificadores, en el orden que respeta las claves foráneas, y conserva las
  categorías, tallas o colores que hayan quedado en uso por otras prendas.
- El script no modifica filas existentes y omite las prendas cuyo slug ya esté cargado, así que
  volver a ejecutarlo no duplica datos.

## Despliegue en Railway

El archivo `railway.json` configura Railpack, ejecuta las migraciones antes del despliegue, inicia FastAPI con el puerto asignado por Railway y valida `/health`.

Configure en Railway al menos `DATABASE_URL`, `JWT_SECRET_KEY`, `APP_ENV=production`, `FRONTEND_URL` y `CORS_ORIGINS`. Las variables SMTP son necesarias para enviar correos reales.

## Rutas principales

- `/api/v1/auth`: registro, login, tokens, contrasena y verificacion.
- `/api/v1/users`: administracion de usuarios y direcciones personales.
- `/api/v1/roles`: roles y permisos.
- `/api/v1/audit-log`: consulta de bitacora.
- `/api/v1/catalog`: catalogo publico y administracion de prendas.
- `/api/v1/organization`: proveedores, ciudades, sucursales y cajas.
- `/api/v1/public/branches`: sucursales visibles sin autenticacion.
- `/health`: estado del servicio.

## Documentacion del proyecto

- `docs/PROJECT_GUIDE.md`: alcance, arquitectura, modelo de datos, seguridad, migraciones y reglas transaccionales.
- `docs/API_CONTRACT.md`: contrato por endpoint, permisos, objetos de entrada, respuestas y ejemplos.
- `docs/TRAZABILIDAD_RF.md`: dónde está implementado cada RF y cada CU en los tres proyectos, y qué falta.
- `../frontend_marketplace_moda/docs/PROJECT_GUIDE.md` y `../mobile_marketplace_moda/docs/PROJECT_GUIDE.md`: los otros dos proyectos.

## Roles iniciales

- `superadmin`
- `admin`
- `store_manager`
- `cashier`
- `client`

Los roles `superadmin` y `admin` reciben los permisos del ciclo I. Inventario, reservas, ventas, pagos, pedidos, envios e IA se agregaran en sus respectivos ciclos.
# FRONTEND_MARKETPLACE_MODA
# BACKEND_MARKETPLACE_MODA
