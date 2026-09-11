# Importación Excel

Router integrado: `/api/v1/bulk/{resource}`. Implementación en `src/shared/bulk`, con lista explícita de recursos y reutilización de servicios de negocio.

- GET `/template` y `/export`: permiso de lectura del módulo.
- POST `/preview`: archivo multipart y mode; valida usando transacción descartable.
- POST `/import`: mode, archivo, preview_digest y confirm. Verifica coincidencia del contenido y vuelve a validar; errores impiden guardar todo el lote.
- El digest comprueba igualdad de contenido; no es una autorización ni sustituye permisos o validación del servidor.

Límites y uso: `../../frontend_marketplace_moda/doc/CARGAS_MASIVAS.md`.

Pruebas aisladas: `../../frontend_marketplace_moda/scripts/test_excel_media.py`. Se comprobaron permisos, exportaciones/plantillas, preview sin persistencia, importación de talla, duplicados, atomicidad de lote mixto, digest diferente y rechazo de fórmulas.

Pendiente: referencias compuestas, campos vacíos en actualización y prueba de volumen. No usar estas pruebas SQLite como evidencia de concurrencia PostgreSQL.
