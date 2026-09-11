# Edición conjunta de prenda y galería

11 de septiembre de 2026.

ProductUpdate admite images opcional. Omitirlo conserva la galería, enviarlo como lista vacía la elimina, y una lista define su contenido final. Cada imagen puede incluir su ID existente, que debe pertenecer al producto y no repetirse. Solo se permite una principal.

El servicio valida los IDs y reconstruye la relación conservando las entidades existentes; las altas y bajas usan la misma transacción que los campos del producto. No se requieren migraciones.

Prueba aislada en `../../frontend_marketplace_moda/scripts/test_excel_media.py`: creación, edición conservando ID, rechazo de imagen ajena sin escritura parcial y eliminación de toda la galería. Pasó junto a las comprobaciones anteriores de Excel y carga de archivos.

Reiniciar el proceso backend para cargar el esquema actualizado. Pendiente limpieza de archivos cargados que no llegaron a asociarse y revisión visual autenticada del frontend.
