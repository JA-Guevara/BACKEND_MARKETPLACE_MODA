# FashionStore API — contrato para frontend

## Convenciones generales

Base local: `http://localhost:8000/api/v1`

Todas las respuestas exitosas usan:

```json
{
  "success": true,
  "message": "Descripción del resultado.",
  "data": {}
}
```

Las operaciones sin contenido responden con `"data": null`. Los listados paginados usan:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

Los errores de negocio, autenticación, autorización y validación usan:

```json
{
  "success": false,
  "error": {
    "code": "validation_error",
    "message": "Los datos enviados no son validos.",
    "details": [
      {"field": "email", "message": "value is not a valid email address", "type": "value_error"}
    ]
  }
}
```

Códigos esperados: `200` correcto, `201` creado, `401` sesión inválida, `403` sin permiso, `404` no encontrado, `409` conflicto y `422` validación. En rutas protegidas se envía `Authorization: Bearer <access_token>`.

## Autenticación

| Método y ruta | Acceso | Objeto de entrada | Salida `data` |
|---|---|---|---|
| `POST /auth/register` | Público | `RegisterRequest` | `AuthUser` |
| `POST /auth/login` | Público | `LoginRequest` | `TokenResponse` |
| `POST /auth/refresh` | Público con refresh | `RefreshRequest` | `TokenResponse` nuevo; rota el refresh anterior |
| `POST /auth/logout` | Público con refresh | `LogoutRequest` | `null` |
| `GET /auth/me` | Usuario autenticado | Sin body | `AuthUser` |
| `POST /auth/forgot-password` | Público | `ForgotPasswordRequest` | `null`; la respuesta no revela si existe el correo |
| `POST /auth/reset-password` | Público | `ResetPasswordRequest` | `null` |
| `POST /auth/change-password` | Usuario autenticado | `ChangePasswordRequest` | `null`; revoca las sesiones |
| `POST /auth/verify-email` | Público | `VerifyEmailRequest` | `null` |
| `POST /auth/resend-verification` | Público | `ResendVerificationRequest` | `null` |

```json
// RegisterRequest
{
  "email": "ana@example.com",
  "password": "RopaSegura!2026",
  "first_name": "Ana",
  "last_name": "Flores",
  "phone": "+59170000000"
}
```

```json
// LoginRequest
{"email": "ana@example.com", "password": "RopaSegura!2026"}
```

```json
// RefreshRequest y LogoutRequest
{"refresh_token": "eyJ..."}
```

```json
// ForgotPasswordRequest y ResendVerificationRequest
{"email": "ana@example.com"}
```

```json
// ResetPasswordRequest
{"token": "token-recibido-por-correo", "new_password": "NuevaClave!2026"}
```

```json
// ChangePasswordRequest
{"current_password": "RopaSegura!2026", "new_password": "NuevaClave!2026"}
```

```json
// VerifyEmailRequest
{"token": "token-recibido-por-correo"}
```

`TokenResponse`:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "email": "ana@example.com",
    "first_name": "Ana",
    "last_name": "Flores",
    "phone": "+59170000000",
    "is_active": true,
    "is_verified": false,
    "last_login_at": "2026-09-05T12:00:00Z",
    "roles": [
      {
        "id": "uuid",
        "code": "client",
        "name": "Cliente",
        "permissions": []
      }
    ]
  }
}
```

## Usuarios y direcciones

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /users` | `users.read` | `page`, `page_size`, `search`, `is_active`, `role_code`, `include_deleted` | `Page<User>` |
| `POST /users` | `users.write` | `UserCreate` | `User` |
| `GET /users/{user_id}` | `users.read` | UUID en ruta | `User` |
| `PATCH /users/{user_id}` | `users.write` | `UserUpdate`, sólo campos enviados | `User` |
| `PUT /users/{user_id}/roles` | `users.write` | `AssignRolesRequest` | `User` |
| `POST /users/{user_id}/activate` | `users.write` | Sin body | `User` |
| `POST /users/{user_id}/deactivate` | `users.write` | Sin body | `User` |
| `POST /users/{user_id}/unlock` | `users.write` | Sin body | `User` |
| `DELETE /users/{user_id}` | `users.write` | Sin body | `null`; borrado lógico |
| `POST /users/{user_id}/restore` | `users.write` | Sin body | `User` |
| `GET /users/me/addresses` | Usuario autenticado | Sin body | `Address[]` |
| `POST /users/me/addresses` | Usuario autenticado | `AddressCreate` | `Address` |
| `PATCH /users/me/addresses/{address_id}` | Propietario | `AddressUpdate` | `Address` |
| `DELETE /users/me/addresses/{address_id}` | Propietario | Sin body | `null` |

```json
// UserCreate
{
  "email": "vendedora@example.com",
  "password": "ClaveTemporal!2026",
  "first_name": "Laura",
  "last_name": "Pérez",
  "phone": "+59171000000",
  "document_number": "12345678",
  "role_ids": ["uuid-del-rol"],
  "is_verified": true
}
```

```json
// UserUpdate
{
  "first_name": "Laura María",
  "phone": "+59172000000",
  "is_verified": true
}
```

```json
// AssignRolesRequest
{"role_ids": ["uuid-del-rol-admin", "uuid-del-rol-encargado"]}
```

```json
// AddressCreate
{
  "label": "Casa",
  "recipient_name": "Ana Flores",
  "phone": "+59170000000",
  "city": "Santa Cruz de la Sierra",
  "address_line": "Av. Principal 123",
  "reference": "Frente a la plaza",
  "is_default": true
}
```

`AddressUpdate` acepta los mismos campos, todos opcionales. `User` agrega estados de bloqueo, fechas, borrado lógico y la lista de roles con permisos.

## Roles y permisos

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /roles` | `roles.read` | `include_inactive=false` | `Role[]` |
| `GET /roles/{role_id}` | `roles.read` | UUID en ruta | `Role` |
| `POST /roles` | `roles.write` | `RoleCreate` | `Role` |
| `PATCH /roles/{role_id}` | `roles.write` | `RoleUpdate` | `Role` |
| `PUT /roles/{role_id}/permissions` | `roles.write` | `SetPermissionsRequest` | `Role` |
| `POST /roles/{role_id}/activate` | `roles.write` | Sin body | `Role` |
| `POST /roles/{role_id}/deactivate` | `roles.write` | Sin body | `Role` |
| `DELETE /roles/{role_id}` | `roles.write` | Sin body | `null` |
| `GET /roles/permissions/all` | `roles.read` | `include_inactive=false` | `Permission[]` |
| `POST /roles/permissions` | `roles.write` | `PermissionCreate` | `Permission` |
| `PATCH /roles/permissions/{permission_id}` | `roles.write` | `PermissionUpdate` | `Permission` |
| `POST /roles/permissions/{permission_id}/activate` | `roles.write` | Sin body | `Permission` |
| `POST /roles/permissions/{permission_id}/deactivate` | `roles.write` | Sin body | `Permission` |
| `DELETE /roles/permissions/{permission_id}` | `roles.write` | Sin body | `null` |

```json
// RoleCreate
{
  "code": "catalog_manager",
  "name": "Gestor de catálogo",
  "description": "Administra prendas y colecciones",
  "permission_ids": ["uuid-catalog-read", "uuid-catalog-write"]
}
```

```json
// RoleUpdate
{"name": "Gestor senior de catálogo", "description": "Administra todo el catálogo"}
```

```json
// SetPermissionsRequest
{"permission_ids": ["uuid-permiso-1", "uuid-permiso-2"]}
```

```json
// PermissionCreate
{
  "code": "reports.read",
  "name": "Consultar reportes",
  "description": "Permite consultar reportes gerenciales",
  "module": "reports"
}
```

`PermissionUpdate` permite `name`, `description` y `module`. El `code` de un permiso y el `code` de un rol no se cambian. Los roles del sistema tienen protección adicional frente a cambios destructivos.

## Catálogo público

Ninguna ruta de esta sección necesita token.

| Método y ruta | Parámetros | Salida `data` |
|---|---|---|
| `GET /catalog/products` | `page=1`, `page_size=24`, `search`, `category_id`, `season_id`, `collection_id`, `size_id`, `color_id`, `brand`, `featured`, `min_price`, `max_price` | `Page<PublicProduct>` |
| `GET /catalog/products/{slug}` | `slug` legible en ruta | `PublicProduct` |
| `GET /catalog/categories` | Sin parámetros | `Category[]` activas |
| `GET /catalog/sizes` | Sin parámetros | `Size[]` activas |
| `GET /catalog/colors` | Sin parámetros | `Color[]` activos |
| `GET /catalog/seasons` | Sin parámetros | `Season[]` activas |
| `GET /catalog/collections` | Sin parámetros | `Collection[]` activas |
| `GET /public/branches` | Sin parámetros | `Branch[]` activas |

Ejemplo de consulta:

```http
GET /api/v1/catalog/products?page=1&page_size=24&search=vestido&size_id=<uuid>&color_id=<uuid>&min_price=100&max_price=500
```

`PublicProduct` contiene `id`, `name`, `slug`, `description`, `brand`, `gender`, `base_price`, `category`, `season`, `collection`, `is_featured`, `variants`, `images` y `ar_assets`. No contiene costos ni relaciones con proveedores.

## Administración de productos

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /catalog/admin/products` | `catalog.read` | Filtros públicos + `page_size=20` + `include_deleted` | `Page<Product>` |
| `POST /catalog/admin/products` | `catalog.write` | `ProductCreate` | `Product` |
| `GET /catalog/admin/products/{product_id}` | `catalog.read` | UUID en ruta | `Product`, incluso eliminado |
| `PATCH /catalog/admin/products/{product_id}` | `catalog.write` | `ProductUpdate` | `Product` |
| `POST /catalog/admin/products/{product_id}/activate` | `catalog.write` | Sin body | `Product`; también restaura |
| `POST /catalog/admin/products/{product_id}/deactivate` | `catalog.write` | Sin body | `Product` |
| `DELETE /catalog/admin/products/{product_id}` | `catalog.write` | Sin body | `null`; borrado lógico |
| `POST /catalog/admin/products/{product_id}/variants` | `catalog.write` | `VariantCreate` | `Product` completo |
| `PATCH /catalog/admin/products/{product_id}/variants/{variant_id}` | `catalog.write` | `VariantUpdate` | `Product` completo |
| `DELETE /catalog/admin/products/{product_id}/variants/{variant_id}` | `catalog.write` | Sin body | `Product` completo |
| `POST /catalog/admin/products/{product_id}/images` | `catalog.write` | `ImageCreate` | `Product` completo |
| `DELETE /catalog/admin/products/{product_id}/images/{image_id}` | `catalog.write` | Sin body | `Product` completo |
| `POST /catalog/admin/products/{product_id}/ar-assets` | `catalog.write` | `ARAssetCreate` | `Product` completo |
| `DELETE /catalog/admin/products/{product_id}/ar-assets/{asset_id}` | `catalog.write` | Sin body | `Product` completo |
| `PUT /catalog/admin/products/{product_id}/suppliers` | `catalog.write` | `SetProductSuppliersRequest` | `Product` completo |

```json
// ProductCreate
{
  "name": "Vestido primavera",
  "slug": "vestido-primavera",
  "description": "Vestido ligero para clima cálido.",
  "brand": "FashionStore",
  "gender": "mujer",
  "base_price": 249.90,
  "category_id": "uuid-categoria",
  "season_id": "uuid-temporada",
  "collection_id": "uuid-coleccion",
  "is_featured": true,
  "variants": [
    {
      "size_id": "uuid-talla",
      "color_id": "uuid-color",
      "sku": "VES-PRI-M-ROJ",
      "barcode": "777000000001",
      "price_override": null
    }
  ],
  "images": [
    {
      "url": "https://cdn.example.com/vestido.jpg",
      "alt_text": "Vestido rojo vista frontal",
      "sort_order": 0,
      "is_primary": true
    }
  ],
  "suppliers": [
    {
      "supplier_id": "uuid-proveedor",
      "supplier_sku": "PROV-VES-101",
      "unit_cost": 120.00,
      "is_primary": true
    }
  ]
}
```

`slug` es opcional y se genera desde el nombre; si ya existe se agrega un sufijo. `variants`, `images` y `suppliers` pueden omitirse y quedan como listas vacías.

```json
// ProductUpdate: todos los campos son opcionales
{
  "name": "Vestido primavera edición 2026",
  "base_price": 269.90,
  "collection_id": "uuid-coleccion",
  "is_featured": false
}
```

```json
// VariantCreate
{
  "size_id": "uuid-talla",
  "color_id": "uuid-color",
  "sku": "VES-PRI-L-AZU",
  "barcode": "777000000002",
  "price_override": 259.90
}
```

```json
// VariantUpdate: todos los campos son opcionales
{"price_override": 279.90, "is_active": false}
```

```json
// ImageCreate
{
  "url": "https://cdn.example.com/vestido-lateral.jpg",
  "alt_text": "Vista lateral",
  "sort_order": 1,
  "is_primary": false
}
```

```json
// ARAssetCreate
{
  "asset_type": "glb",
  "asset_url": "https://cdn.example.com/ar/vestido.glb",
  "preview_url": "https://cdn.example.com/ar/vestido-preview.jpg"
}
```

```json
// SetProductSuppliersRequest; PUT reemplaza la lista completa
{
  "suppliers": [
    {
      "supplier_id": "uuid-proveedor",
      "supplier_sku": "PROV-VES-101",
      "unit_cost": 120.00,
      "is_primary": true
    }
  ]
}
```

## Datos maestros del catálogo

Para cada recurso `categories`, `sizes`, `colors`, `seasons` y `collections` existen estas operaciones:

| Método y patrón | Permiso | Resultado |
|---|---|---|
| `GET /catalog/admin/{recurso}?include_inactive=true` | `catalog.read` | Lista administrativa |
| `POST /catalog/admin/{recurso}` | `catalog.write` | Crea el registro |
| `GET /catalog/admin/{recurso}/{entity_id}` | `catalog.read` | Obtiene un registro |
| `PATCH /catalog/admin/{recurso}/{entity_id}` | `catalog.write` | Actualiza campos enviados |
| `POST /catalog/admin/{recurso}/{entity_id}/activate` | `catalog.write` | Activa |
| `POST /catalog/admin/{recurso}/{entity_id}/deactivate` | `catalog.write` | Desactiva si no está en uso |
| `DELETE /catalog/admin/{recurso}/{entity_id}` | `catalog.write` | Elimina si no está en uso |

Entradas:

```json
// CategoryCreate
{"name": "Vestidos", "slug": "vestidos", "description": "Vestidos para mujer", "parent_id": null}
```

```json
// SizeCreate
{"code": "M", "name": "Mediana", "sort_order": 20}
```

```json
// ColorCreate
{"name": "Rojo", "hex_code": "#FF0000"}
```

```json
// SeasonCreate
{
  "name": "Primavera 2026",
  "description": "Temporada primavera",
  "start_date": "2026-09-21",
  "end_date": "2026-12-20"
}
```

```json
// CollectionCreate
{
  "name": "Flores de Oriente",
  "description": "Colección primavera",
  "season_id": "uuid-temporada"
}
```

Los objetos `*Update` tienen los mismos campos opcionales. Una categoría no puede ser su propio padre; las fechas deben ser coherentes y una colección/producto debe respetar su temporada.

## Proveedores, ciudades, sucursales y cajas

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /organization/cities` | `branches.read` | `include_inactive` | `City[]` |
| `POST /organization/cities` | `branches.write` | `CityCreate` | `City` |
| `GET /organization/cities/{entity_id}` | `branches.read` | UUID | `City` |
| `PATCH /organization/cities/{entity_id}` | `branches.write` | `CityUpdate` | `City` |
| `POST /organization/cities/{entity_id}/activate` | `branches.write` | Sin body | `City` |
| `POST /organization/cities/{entity_id}/deactivate` | `branches.write` | Sin body | `City` |
| `DELETE /organization/cities/{entity_id}` | `branches.write` | Sin body | `null` |
| `GET /organization/suppliers` | `suppliers.read` | `search`, `include_inactive`, `include_deleted` | `Supplier[]` |
| `POST /organization/suppliers` | `suppliers.write` | `SupplierCreate` | `Supplier` |
| `GET /organization/suppliers/{entity_id}` | `suppliers.read` | `include_deleted` | `Supplier` |
| `PATCH /organization/suppliers/{entity_id}` | `suppliers.write` | `SupplierUpdate` | `Supplier` |
| `POST /organization/suppliers/{entity_id}/activate` | `suppliers.write` | Sin body | `Supplier`; también restaura |
| `POST /organization/suppliers/{entity_id}/deactivate` | `suppliers.write` | Sin body | `Supplier` |
| `DELETE /organization/suppliers/{entity_id}` | `suppliers.write` | Sin body | `null`; borrado lógico |
| `GET /organization/branches` | `branches.read` | `include_inactive`, `include_deleted` | `Branch[]` |
| `POST /organization/branches` | `branches.write` | `BranchCreate` | `Branch` |
| `GET /organization/branches/{entity_id}` | `branches.read` | `include_deleted` | `Branch` |
| `PATCH /organization/branches/{entity_id}` | `branches.write` | `BranchUpdate` | `Branch` |
| `POST /organization/branches/{entity_id}/activate` | `branches.write` | Sin body | `Branch`; también restaura |
| `POST /organization/branches/{entity_id}/deactivate` | `branches.write` | Sin body | `Branch` |
| `DELETE /organization/branches/{entity_id}` | `branches.write` | Sin body | `null`; borrado lógico |
| `GET /organization/cash-points` | `branches.read` | `branch_id`, `include_inactive`, `include_deleted` | `CashPoint[]` |
| `POST /organization/cash-points` | `branches.write` | `CashPointCreate` | `CashPoint` |
| `GET /organization/cash-points/{entity_id}` | `branches.read` | `include_deleted` | `CashPoint` |
| `PATCH /organization/cash-points/{entity_id}` | `branches.write` | `CashPointUpdate` | `CashPoint` |
| `POST /organization/cash-points/{entity_id}/activate` | `branches.write` | Sin body | `CashPoint`; también restaura |
| `POST /organization/cash-points/{entity_id}/deactivate` | `branches.write` | Sin body | `CashPoint` |
| `DELETE /organization/cash-points/{entity_id}` | `branches.write` | Sin body | `null`; borrado lógico |

```json
// CityCreate
{"name": "Santa Cruz de la Sierra", "department": "Santa Cruz", "country": "Bolivia"}
```

```json
// SupplierCreate
{
  "business_name": "Textiles del Oriente S.R.L.",
  "trade_name": "Textiles Oriente",
  "tax_id": "NIT-123456",
  "contact_name": "María Suárez",
  "email": "ventas@textiles.example",
  "phone": "+59133000000",
  "address": "Parque Industrial Mz. 5",
  "city": "Santa Cruz de la Sierra",
  "notes": "Entrega los lunes"
}
```

```json
// BranchCreate
{
  "code": "SCZ-01",
  "name": "Sucursal Central",
  "city_id": "uuid-ciudad",
  "address": "Av. Principal 123",
  "phone": "+59133000001",
  "latitude": -17.7833,
  "longitude": -63.1821,
  "opening_hours": {
    "monday": {"open": "09:00", "close": "20:00"},
    "sunday": null
  }
}
```

```json
// CashPointCreate
{"branch_id": "uuid-sucursal", "code": "CAJA-01", "name": "Caja principal"}
```

Los objetos de actualización contienen los mismos campos opcionales. El código de sucursal y el de caja se normalizan a mayúsculas.

## Bitácora

| Método y ruta | Permiso | Parámetros | Salida `data` |
|---|---|---|---|
| `GET /audit-log` | `audit.read` | `page=1`, `page_size=50`, `actor_user_id`, `action`, `entity_type`, `date_from`, `date_to` | `Page<AuditEvent>` |
| `GET /audit-log/{event_id}` | `audit.read` | UUID en ruta | `AuditEvent` |

`date_from` y `date_to` usan ISO 8601, por ejemplo `2026-09-01T00:00:00-04:00`. `AuditEvent` contiene `id`, `actor_user_id`, `actor_name`, `actor_email`, `action`, `entity_type`, `entity_id`, `description`, `metadata_`, `ip_address`, `user_agent` y `created_at`. `actor_name`/`actor_email` y `ip_address` se resuelven automáticamente (usuario que originó la acción y IP del request) para todos los módulos, no solo autenticación.

## Estado y OpenAPI

`GET /health` no usa el prefijo `/api/v1` y responde:

```json
{"status": "ok"}
```

Swagger UI en `/docs` y el contrato OpenAPI procesable en `/openapi.json` son la fuente ejecutable del esquema. Este documento explica las decisiones de integración y ejemplos; si una herramienta genera tipos TypeScript, debe hacerlo desde `/openapi.json`.
