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
Copy-Item .env.example .env
```

Configure `DATABASE_URL`, `JWT_SECRET_KEY`, CORS y SMTP en `.env` antes de desplegar.

## Migraciones

Aplicar las migraciones:

```powershell
alembic upgrade head
```

Despues de aplicar la migracion, cree el primer superadministrador:

```powershell
python scripts/create_superadmin.py --email admin@example.com --password "UnaClaveSegura!2026" --first-name Admin --last-name Principal
```

## Ejecucion

```powershell
uvicorn src.main:app --reload --port 8000
```

Documentacion interactiva: `http://localhost:8000/docs`.

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

- `docs/PROJECT_GUIDE.md`: alcance, arquitectura, modelo de datos, seguridad, despliegue y trazabilidad del ciclo I.
- `docs/API_CONTRACT.md`: contrato por endpoint, permisos, objetos de entrada, respuestas y ejemplos para el frontend.

## Roles iniciales

- `superadmin`
- `admin`
- `store_manager`
- `cashier`
- `client`

Los roles `superadmin` y `admin` reciben los permisos del ciclo I. Inventario, reservas, ventas, pagos, pedidos, envios e IA se agregaran en sus respectivos ciclos.
# FRONTEND_MARKETPLACE_MODA
# BACKEND_MARKETPLACE_MODA
