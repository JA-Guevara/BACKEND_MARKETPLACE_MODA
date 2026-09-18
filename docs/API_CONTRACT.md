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

## Carrito y pedidos

El carrito vive en el servidor, asociado al usuario: se conserva entre dispositivos y no depende del navegador. Los precios y totales **siempre** los calcula el backend a partir del catálogo; el cliente solo manda identidades y cantidades.

| Método y ruta | Acceso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /commerce/branches` | Público | Sin parámetros | `{id, name, address}[]` activas |
| `GET /commerce/recommendations` | Público, mejora con sesión | `limit=8` | `RecommendedProduct[]` |
| `PATCH /commerce/profile` | Autenticado | `ProfileUpdate` | Datos personales del cliente |
| `GET /commerce/cart` | Autenticado | `branch_id` opcional | `Cart` |
| `PUT /commerce/cart/items/{variant_id}` | Autenticado | `{quantity: 1..99}` | `null` |
| `DELETE /commerce/cart/items/{variant_id}` | Autenticado | Sin body | `null` |
| `POST /commerce/orders` | Autenticado | `CheckoutOrder` | `Order` (201) |
| `GET /commerce/orders` | Autenticado | `limit=100`, `offset=0` | `Order[]` propios |
| `GET /commerce/orders/{order_id}` | Autenticado, dueño | UUID en ruta | `Order` |
| `POST /commerce/orders/{order_id}/cancel` | Autenticado, dueño | Sin body | `Order` |

`Cart` contiene `items`, `total` y `currency`. Cada ítem trae `variant_id`, `product_id`, `name`, `sku`, `size`, `color`, `image_url`, `unit_price`, `quantity`, `available` y `line_total`.

`Order` contiene `id`, `number`, `customer_email`, `status`, `payment_status`, `payment_method`, `payment_reference`, `total`, `currency`, `address`, `items`, `tracking`, `carrier`, `tracking_number`, `paid_at` y `created_at`. **Nunca** expone `stripe_session_id` ni `stripe_url`: se entregan solo en la respuesta del checkout.

Estados de `status`: `pending_payment → paid → processing → shipped → delivered`, más `cancelled` y `expired` como salidas. Las transiciones administrativas permitidas están en `src/ventas_pagos/domain/states.py` y el backend rechaza cualquier otra con `409`.

**Efecto sobre existencias**: crear el pedido **descuenta** las unidades de la sucursal en el mismo momento, con movimiento `web_order_hold`. Cancelar o vencer las devuelve con `web_order_release`. Un pedido nunca queda apartado a medias: si falla una prenda, se revierten todas.

Solo se puede cancelar un pedido en `pending_payment`; en otro estado responde `409`.

## Pagos

| Método y ruta | Acceso | Entrada | Salida `data` |
|---|---|---|---|
| `POST /commerce/orders/{order_id}/checkout` | Autenticado, dueño | Sin body | `{session_id, url}` o `{status, url: null}` si ya estaba pagado |
| `POST /commerce/orders/{order_id}/payment-status` | Autenticado, dueño | Sin body | `Order` reconciliado |
| `POST /commerce/admin/orders/{order_id}/payment-status` | `commerce.write` | Sin body | `Order` reconciliado |
| `POST /commerce/admin/orders/{order_id}/payment` | `commerce.write` | `ManualPayment` | `Order` |
| `PATCH /commerce/admin/orders/{order_id}/tracking` | `commerce.write` | `TrackingUpdate` | `Order` |
| `GET /commerce/admin/orders` | `commerce.read` | `limit`, `offset`, `status`, `branch_id`, `channel` (`web`/`pos`), `q` (número o correo) | `Order[]` con `has_open_return` |
| `GET /commerce/admin/orders/{order_id}/receipt` | `commerce.write` | UUID en ruta | Comprobante imprimible |
| `POST /commerce/stripe/webhook` | Firma de Stripe | Evento firmado | `{received: true}` |

`POST .../payment-status` es la **red de seguridad** del pago: consulta Stripe desde el servidor y acredita el pedido si el cobro se completó, o lo vence si la sesión expiró. Existe porque volver del checkout en el navegador no prueba nada, y porque un webhook puede llegar tarde. Es también lo que usa la app móvil al regresar del navegador. No acredita dos veces: comparte la misma transición que el webhook.

`TrackingUpdate` exige `carrier` y `tracking_number` cuando el nuevo estado es `shipped`.

El webhook verifica la firma de Stripe y descarta eventos repetidos por `event_id`; un reintento de Stripe no vuelve a mover el pedido ni reenvía el aviso al cliente.

## Venta presencial y existencias

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /commerce/admin/cash-points` | `commerce.write` | `branch_id` | Cajas activas de la sucursal |
| `POST /commerce/admin/pos/sales` | `commerce.write` | `POSSale` | `Order` ya entregado y pagado (201) |
| `GET /commerce/admin/pos/orders` | `commerce.write` | `number` de la venta | `{order, can_request, reason, units, returns}` |
| `POST /commerce/admin/pos/returns` | `commerce.write` | `CounterReturn` | `OrderReturn` ya cerrada (201) |
| `GET /commerce/admin/pos/stock` | `commerce.write` | `branch_id`, `search` | Existencias para la pantalla de caja |
| `GET /commerce/admin/stock` | `stock.read` | `branch_id`, `search`, paginación | Existencias por variante y sucursal |
| `PUT /commerce/admin/stock/{variant_id}` | `stock.write` | `StockQuantity` | Existencia ajustada |
| `GET /commerce/admin/stock/movements` | `stock.read` | `branch_id`, `variant_id`, `kind`, fechas | Movimientos con actor |
| `POST /commerce/admin/stock/{variant_id}/movements` | `stock.write` | `StockEntry` | Movimiento registrado (201) |

`POSSale.payment_method` admite `cash`, `qr`, `card` y `transfer` (RF18). Solo el efectivo da vuelto; los otros tres se cobran por el importe exacto y la referencia guarda el rastro del cobro: el identificador de la transacción del QR, el voucher del terminal o el número de comprobante. `ManualPayment` admite los mismos cuatro, porque el pago de un pedido web también se puede recibir en el local.

`POSSale` lleva `client_request_id`: la misma clave con los mismos datos devuelve la venta ya registrada en vez de cobrar dos veces; con datos distintos responde `409`. El servidor toma los precios del catálogo, nunca del cliente.

Cada cambio de existencias deja un movimiento con saldo anterior, saldo posterior, motivo y quién lo hizo. Los tipos son `web_order_hold`, `web_order_release`, `pos_sale`, `reservation_hold`, `reservation_release`, `return_received`, `receipt`, `issue` y `adjustment`.

`CounterReturn` = `{order_id, reason, items, note?, client_request_id}`. Es la devolución del mostrador: nace en `completed` y reintegra el stock en el acto, porque el cliente entrega la prenda y cobra en el momento. La clave idempotente evita reintegrar dos veces ante un doble clic.

## Devoluciones (CU19)

Se devuelve un pedido **entregado y pagado**, dentro de los 15 días desde la entrega, y solo las unidades que no estén ya en otra devolución vigente.

| Método y ruta | Acceso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /commerce/orders/{order_id}/returns` | Autenticado, dueño | UUID en ruta | `{can_request, reason, units, returns}` |
| `POST /commerce/orders/{order_id}/returns` | Autenticado, dueño | `ReturnRequest` | `OrderReturn` (201) |
| `GET /commerce/returns` | Autenticado | `limit=100`, `offset=0` | `OrderReturn[]` propias |
| `GET /commerce/admin/returns` | `commerce.read` | `status`, `branch_id`, `q` (número de pedido), `limit`, `offset` | `OrderReturn[]` con contexto del pedido |
| `PATCH /commerce/admin/returns/{return_id}` | `commerce.write` | `ReturnResolution` | `OrderReturn` |

`ReturnRequest` = `{reason (5..500), items: [{variant_id, quantity}], client_request_id?}`. La clave idempotente evita abrir dos devoluciones si el formulario se reenvía.

`ReturnResolution` = `{status: approved|rejected|completed, note?}`. **Rechazar exige nota**: es lo que el cliente lee como explicación.

En la bandeja de administración cada devolución llega además con `order_number`, `customer_name`, `customer_email`, `branch_name` y `sales_channel`: una devolución sin esos datos no se puede resolver sin ir a buscar el pedido por UUID. `has_open_return` en el listado de pedidos evita abrirlos uno por uno para ver cuáles tienen una devolución sin resolver.

`OrderReturn` contiene `id`, `order_id`, `branch_id`, `status`, `reason`, `items` (copia con el precio al momento de la compra), `refund_amount`, `currency`, `resolution_note`, `resolved_at` y `created_at`.

Circuito: `requested → approved → completed`, con `rejected` posible desde los dos primeros. **Aprobar no devuelve stock**: las unidades vuelven al inventario recién en `completed`, con movimiento `return_received`, porque es cuando las prendas están físicamente de nuevo en la sucursal. Un rechazo libera las unidades comprometidas y el cliente puede volver a pedirlas.

`units` de la consulta indica cuántas unidades quedan por devolver de cada variante; el servidor vuelve a validarlo al recibir la solicitud.

## Reservas de probador

| Método y ruta | Acceso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `POST /reservations` | Autenticado | `CrearReservaRequest` | `Reservation` (201) |
| `GET /reservations/availability` | Autenticado | `branch_id`, `variant_id` (repetible), `quantity` (repetible) | Disponibilidad por variante |
| `GET /reservations` | Autenticado | Paginación | `Page<Reservation>` propias |
| `GET /reservations/{reservation_id}` | Autenticado, dueño | UUID en ruta | `Reservation` |
| `POST /reservations/{reservation_id}/cancel` | Autenticado, dueño | Sin body | `Reservation` |
| `GET /reservations/admin/all` | `reservations.read` | `status`, `branch_id`, fechas, paginación | `Page<Reservation>` |
| `PATCH /reservations/admin/{reservation_id}/status` | `reservations.write` | `{status, note?}` | `Reservation` |

`availability` se declara **antes** que `/{reservation_id}` en el router: al revés, FastAPI intentaría interpretar la palabra `availability` como un UUID y respondería `422`.

`CrearReservaRequest` = `{branch_id, scheduled_at, items: [{variant_id, quantity 1..10}], notes?, client_key?}`. Hasta 20 variantes distintas tras agrupar repetidas (RF09). El horario se valida contra la agenda de atención.

Estados: `pending → confirmed → ready → attended`, más `cancelled`. Crear la reserva **aparta** las unidades (`reservation_hold`); cancelar o atender las libera (`reservation_release`). Una reserva anterior a la migración de inventario no aparta nada y tampoco devuelve nada: el campo `inventory_held` lo distingue.

Si la sucursal no tiene la talla pedida, la creación responde `422` nombrando la prenda y la talla, en vez de hacer viajar al cliente.

`client_key` hace la creación idempotente: la misma clave con el mismo detalle devuelve la reserva ya registrada; con detalle distinto avisa en vez de devolver en silencio la anterior.

## Probador virtual

| Método y ruta | Acceso | Entrada | Salida `data` |
|---|---|---|---|
| `POST /vestidor/sessions` | Autenticado | `{product_id, color_id?, variant_id?}` | Recurso y anclajes de la prenda |
| `GET /vestidor/admin/products/{product_id}/assets` | `catalog.read` | UUID en ruta | Recursos preparados del producto |
| `POST /vestidor/admin/products/{product_id}/assets` | `catalog.write` | `{color_id}` | Recurso preparado |
| `PATCH /vestidor/admin/assets/{asset_id}` | `catalog.write` | Corrección manual de anclajes | Recurso ajustado |

La preparación recorta el fondo de la foto y calcula los puntos de anclaje (hombros, cadera, largo) una sola vez por producto y color, no por talla: la foto cambia con el color, no con el talle. Si el fondo no es liso, conserva la foto original en vez de romper la silueta, y el ajuste manual permite corregir lo que el análisis propuso.

Un color sin recurso preparado avisa explícitamente en lugar de usar el de otro color.

## Reportes y asistente de IA

| Método y ruta | Permiso | Entrada / parámetros | Salida `data` |
|---|---|---|---|
| `GET /analytics/dashboard` | `dashboard.read` | Filtros de fecha y sucursal | KPIs y series |
| `POST /analytics/insights` | `dashboard.read` | `InsightsRequest` | Lectura en lenguaje natural |
| `POST /analytics/assistant/interpret` | `dashboard.read` | `InterpretRequest` | Intención detectada |
| `POST /analytics/assistant/explain` | `dashboard.read` | `ExplainRequest` | Explicación de las métricas |
| `POST /analytics/assistant/execute` | `dashboard.read` | `AssistantToolRequest` | Resultado de la herramienta |
| `GET /analytics/reports/export` | `dashboard.read` | `type`, filtros, `format` | Archivo CSV/XLSX/PDF |
| `POST /analytics/reports/export-multiple` | `dashboard.read` | `MultiExportRequest` | Archivo combinado |
| `POST /commerce/assistant` | Autenticado | `{message, context?}` | `{available, reply}` |

El asistente ejecuta únicamente herramientas de una lista cerrada y valida sus parámetros; una herramienta no autorizada se rechaza. Cada operación queda en bitácora con el correo del actor y no se audita dos veces por el mismo `request_id`.

Sin `AI_API_KEY` configurada, `/commerce/assistant` responde `{available: false}` con un mensaje útil en lugar de fallar.

## Avisos por correo

No son endpoints: son efectos de las operaciones anteriores (CU15 y RF11).

| Operación | A quién avisa |
|---|---|
| Crear pedido, confirmar pago, preparar, despachar, entregar, cancelar, vencer | Cliente |
| Venta en caja con correo cargado | Cliente (comprobante) |
| Crear pedido web | Cliente **y** sucursal (tiene prendas apartadas por preparar) |
| Crear reserva | Cliente **y** sucursal (RF11) |
| Solicitar una devolución | Cliente **y** gestión (alguien tiene que resolverla) |
| Confirmar, preparar, atender o cancelar una reserva | Cliente |
| Solicitar, aprobar, rechazar o cerrar una devolución | Cliente |

Cada aviso viaja en dos versiones (HTML con el diseño de la tienda y texto plano). La venta en caja recibe el **comprobante** de la compra, no un aviso de estado, y la devolución cerrada informa el importe reembolsado y por qué medio vuelve.

El envío es "lo mejor posible": si el servidor de correo está caído o sin configurar, la operación igual se registra y en bitácora queda `notificaciones.email_enviado` o `notificaciones.email_fallido` con el destinatario. Un correo nunca revierte una venta.

El destinatario del aviso a la sucursal es su campo `notification_email`; si está vacío, se usa `OPERATIONS_EMAIL`.

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
