# FashionStore Backend — guía del proyecto

## 1. Propósito y alcance actual

FashionStore es el backend de una plataforma de comercio electrónico de ropa con catálogo público como página principal. El acceso no comienza en una pantalla de login: cualquier visitante puede consultar productos, categorías, tallas, colores, temporadas, colecciones y sucursales. La autenticación se solicita cuando una operación es personal o administrativa.

Esta entrega deja implementado el ciclo I descrito en la documentación funcional:

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

Los módulos de inventario por sucursal, reservas, probador virtual, ventas, pagos, pedidos, envíos, reseñas e IA pertenecen a los ciclos posteriores. Sus carpetas existentes son una referencia de expansión, pero no se publican rutas incompletas.

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
- `src/shared`: respuestas, paginación y excepciones comunes.
- `src/config/routes.py`: composición única de rutas del API.

`src/usuarios` y `src/roles` continúan como componentes internos ya estables y se exponen desde `usuarios_catalogo`. Esto conserva compatibilidad sin duplicar lógica.

## 3. Modelo de datos del ciclo I

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
Copy-Item .env.example .env
```

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
| `SMTP_*` | Servidor de correo para verificación y recuperación |

Si SMTP no está configurado, el usuario se registra, pero no se envía el correo. En producción deben configurarse SMTP, HTTPS, una clave JWT real y orígenes CORS exactos.

## 7. Migraciones y primer arranque

Alembic tiene una cadena lineal:

1. `20260903_0001`: autenticación, usuarios, roles, permisos, direcciones y bitácora.
2. `20260905_0002`: catálogo, proveedores, ciudades, sucursales, cajas y nuevos permisos.

Aplicar todo:

```powershell
.venv\Scripts\alembic.exe upgrade head
```

Consultar el estado:

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe heads
```

Crear el primer superadministrador después de migrar:

```powershell
.venv\Scripts\python.exe scripts/create_superadmin.py --email admin@example.com --password "UnaClaveSegura!2026" --first-name Admin --last-name Principal
```

El script no debe ejecutarse con una contraseña de ejemplo en un entorno real.

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

## 12. Siguiente ciclo sugerido

El próximo bloque debería construir inventario por variante y sucursal, movimientos/kardex y disponibilidad. Reservas, carrito, pedidos y ventas deben consumir esa única fuente de existencias para evitar dobles reservas o sobreventa. Después pueden conectarse pagos, envíos, probador virtual, recomendaciones y reportes.
