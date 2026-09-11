# Coordinación de la sesión comercial

El usuario autorizó agentes para completar los pendientes. El reparto y orden de reanudación se conserva en `../../frontend_marketplace_moda/doc/COORDINACION.md`.

commerce_finish tiene a cargo backend, migración, permisos, routers, metadata y fixture de base temporal. No aplicar migraciones a la base real durante las pruebas ni realizar cobros externos. Los resultados comerciales deben guardarse en COMERCIO.md; el estado general y limitaciones, en ESTADO_ACTUAL.md e HISTORIAL.md.

La interfaz se desarrolla simultáneamente contra `/commerce` y `/analytics`. Cualquier cambio de contrato requiere avisar al responsable frontend y actualizar pruebas/documentación antes del cierre.
