# Carrito publicado — 12/09/2026

Health y sucursales publicados responden 200; carrito sin autorización responde 401; preflight del carrito permite origen frontend y Authorization. No se ha reproducido la petición autenticada del usuario. Se solicitaron logs para confirmar la excepción.

Se agregó manejador SQLAlchemyError: 503 JSON con referencia y CORS. Logs identifican tipo, SQLSTATE y tabla sin copiar consultas o credenciales. La prueba con OperationalError simulada pasa y confirma que no se filtran detalles privados al cliente.

3 pruebas comerciales aprobadas. Esto mejora la respuesta ante fallos; no corrige por sí solo una base desactualizada o inaccesible. railway.json ya incluye migraciones antes de desplegar. Revisar logs y versión de migración efectiva antes de tomar medidas sobre producción.

Cambios locales, sin despliegue ni modificación de la base real. Evidencia y checklist visual en `../../frontend_marketplace_moda/doc/DIAGNOSTICO_RAILWAY_Y_DISENO.md`.
