# Contrato del probador virtual y estado de verificación

## Actualización 16/09 (Etapas 5–6)
- `PATCH /api/v1/catalog/admin/products/{product_id}/ar-assets/{asset_id}` (NUEVO):
  schema `ARAssetUpdate` (`asset_url`, `preview_url`, `is_active` opcionales). Regla por
  defecto: al activar una prenda, las demás del mismo `asset_type` del producto quedan
  inactivas (`CatalogService.update_ar_asset`). Probado en
  `tests/unit/catalog/test_cycle_one_services.py`.
- POST /api/v1/media/images (permiso catalog.write) permite subir la imagen del probador (PNG/JPEG/WebP) y ahora lo usa el formulario del editor de producto.
- El cliente (vestidor Angular) sigue usando `POST /api/v1/vestidor/sessions` sin cambios;
  el seguimiento corporal ocurre íntegramente en el navegador (MediaPipe vía CDN), el
  backend no recibe fotogramas ni posturas.
- Suite unitaria completa: **71 passed**.

Fecha 15/09 (histórico de la tanda anterior):

Fecha: 15/09/2026. Se revisó el backend existente y se añadieron pruebas; no se modificaron sus rutas, modelos ni migraciones en esta sesión.

## Implementación existente

`POST /api/v1/vestidor/sessions` recibe `{product_id}` y exige un usuario autenticado. `VirtualFittingService` rechaza productos inexistentes, inactivos o eliminados y resuelve el primer recurso activo de tipo `image_overlay`. No renderiza GLB/GLTF/USDZ aunque el catálogo permita almacenarlos.

`IniciarExperiencia` registra `probador_virtual.session_started` con actor autenticado, producto y tipo de recurso, realiza commit y devuelve la referencia del recurso mediante `ApiResponse`.

No existe una sesión de video persistida. El nombre `/sessions` identifica la apertura de la experiencia y su traza, no una carga o grabación de cámara. El endpoint no verifica que la URL externa contenga una imagen visible; esa carga debe verificarse en el cliente.

## Pruebas ejecutadas

Comando: `.venv\Scripts\python.exe -B -m pytest tests/unit/probador_virtual/test_vestidor_contract.py -q -p no:cacheprovider`.

Resultado: **4 aprobadas**, con una advertencia preexistente de deprecación Starlette/AnyIO.

- Selección de imagen activa frente a recurso 3D e imagen inactiva; evento persistido y actor correcto.
- Ausencia de imagen activa: 404 y sin evento de éxito.
- Producto inactivo o inexistente: 404 y sin evento de éxito.
- Identificador inválido: 422; sin autenticación: 401.

Se utilizan rutas reales con dependencias sustituidas por SQLite en memoria y un usuario ficticio. No se conectó a la base del servidor, Stripe, IA ni SMTP. No se restauraron los antiguos scripts QA eliminados previamente por otra sesión.

## Integración frontend y límites

El frontend corregido pide cámara por acción explícita y envía la traza después de iniciar la reproducción si hay sesión. Un fallo del POST se comunica sin bloquear el video. Una vista pública sin sesión no produce una traza autenticada.

Estado actual: superposición 2D de ajuste manual y recurso por producto. Pendientes: pruebas físicas en móvil/despliegue, asociación por variante/color, calibración y seguimiento corporal. No declarar validación de talla, simulación 3D ni retención de imágenes personales.

Consultar `../../frontend_marketplace_moda/doc/PROBADOR_VIRTUAL.md` para guía de prueba manual, archivos modificados, resultados frontend y plan de continuación.
