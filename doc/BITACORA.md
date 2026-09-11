# Bitácora — estado al 10/09/2026

## Implementado
- Lectura protegida por audit.read; búsqueda actor_query por nombre completo o correo sin requerir users.read. Se mantiene actor_user_id por compatibilidad.
- Actor explícito del servicio y, si falta, usuario autenticado de la petición. No se identifica una persona por datos proporcionados por el cliente.
- Contexto aislado por petición, compartido con los trabajadores síncronos de FastAPI y restaurado en finally. UUID de correlación generado en servidor en metadata_.request_id.
- IP de scope.client y agente del navegador limitado a 500 caracteres. No se confía directamente en X-Forwarded-For.
- Orden estable por fecha descendente e ID descendente para empates.

## Despliegue y límites
En conexión directa se guarda la IP del cliente TCP. Detrás de proxy, configurar Uvicorn --proxy-headers --forwarded-allow-ips con las IP concretas del proxy confiable; nunca usar * con acceso directo público al backend. El proxy debe reemplazar cabeceras de reenvío del cliente. En desarrollo localhost es la IP esperada.
Los eventos históricos no pueden reconstruir actor/IP que no se registraron. Nombre y correo se resuelven desde users; usuarios eliminados físicamente pueden perder esa relación. No se añade una migración de snapshots históricos en este cambio. Sin usuario asociado puede representar operaciones anónimas o internas; no se inventa identidad.
El detalle expone metadatos ya definidos por cada servicio y un identificador de solicitud, nunca se captura automáticamente el cuerpo HTTP, tokens o contraseñas. Los futuros servicios deben registrar sólo metadatos de negocio pertinentes y pasar actor explícito en trabajos fuera de HTTP.

## Validación
Pruebas tests/unit/bitacora/test_audit_context.py: paso del actor entre trabajadores, limpieza del contexto ante errores, rechazo de IP reenviada no confiable, persistencia y búsqueda por nombre/correo (incluye comodín literal). 3 aprobadas.
