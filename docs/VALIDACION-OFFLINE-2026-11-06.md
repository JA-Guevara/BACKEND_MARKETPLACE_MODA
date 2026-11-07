# Revisión funcional sin conexión · 06/11/2026

Alcance: requisitos offline del documento «Examen Parcial-2 - Sistemas 2 - S2-2026.pdf», apartados 5.3–5.4, 6.2–6.4 y 7.2 (páginas 3–5). La auditoría Word y la comparativa Excel se leyeron como evidencia histórica; no se modificaron ni se tomaron sus instrucciones como autorización adicional. Esta revisión no certifica el resto del examen.

## Causas comprobadas y correcciones

Había almacenamiento y servicios de servidor, pero faltaba la pantalla de venta en ambos clientes. También faltaban las pantallas móviles de operaciones y conflictos. La descarga no entregaba cajas y caducidad de precios; la web enviaba lotes incompletos y consultaba estados con un método equivocado. El servicio web de sincronización no arrancaba automáticamente. Navegar sin red podía vaciar la selección de reserva por una recarga reactiva del perfil. La lista de reservas fallaba al convivir con ventas sin payload duplicado.

Se añadieron pantallas y navegación de venta en efectivo, comprobantes provisionales y consulta de resultados; se conectó la portada web al catálogo local, se corrigieron los contratos de envío/consulta/resolución y se preservaron las operaciones ante fallos de red y reaperturas. La cola referencia los documentos de venta y reconstruye el envío sin duplicar sus líneas. Una operación enviada tiene un período de exclusión para evitar envíos paralelos y puede recuperarse tras una interrupción. Las operaciones rechazadas y los conflictos permanecen consultables. La sincronización manual y automática actualiza los estados visibles.

El servidor valida responsable, empresa, sucursal autorizada, caja activa, cantidades, suma de líneas, efectivo y forma de pago. Bloquea las existencias al confirmar. Los conflictos de reserva también pueden ajustarse; la fecha local original de la venta se conserva al resolver. La suscripción en solo lectura conserva el contrato RETRY/`subscription_read_only`, sin perder la operación. La descarga, los documentos, las colas y el historial web se filtran por cuenta y empresa.

## Matriz de comprobación

| Requisito | Resultado y evidencia |
| --- | --- |
| Catálogo, variantes, precios y existencias descargados | PWA reabierta sin red mostrando su catálogo; catálogo Flutter con pruebas de pantalla y SQLite |
| Reservas sin conexión | Reserva PWA guardada junto a una venta y confirmada al volver la red; pruebas existentes de reserva móvil y persistencia |
| Venta de contado | Nuevas pantallas web y Flutter con caja, líneas, cantidades, total, recibido, vuelto y folio provisional |
| Cierre y reapertura | PWA cerrada y reabierta sin red; venta SQLite cerrada y abierta desde archivo con el mismo identificador |
| Cola e identificación única | Envío reconstruido desde documentos; recuperación de envíos interrumpidos, reintentos y estados persistidos |
| Sin duplicaciones | Ensayo PWA con sincronización repetida; PostgreSQL real con dos envíos concurrentes del mismo UUID |
| Inventario consistente | PostgreSQL real: dos ventas distintas de 15 unidades sobre 20 dejan una confirmada, otra en conflicto y stock 5 |
| Conflictos y resultados | Ensayo PWA ajusta una venta de 3 a 1 unidad y actualiza el estado local mediante POST de consulta; prueba backend ajusta una reserva |
| Aislamiento de empresas | Empresa B no ve catálogo ni operaciones de A en el ensayo PWA; pruebas de snapshot por sucursales y conflicto ajeno 404 |
| APK | Compilación Android debug correcta; falta ensayo en teléfono físico con modo avión y suspensión del sistema |

## Verificación ejecutada

- Backend: 763 pruebas unitarias aprobadas con Python 3.12; 2 pruebas de concurrencia aprobadas en bases PostgreSQL locales efímeras.
- Web: 662 pruebas aprobadas y compilación de producción correcta.
- Flutter: 307 pruebas aprobadas y `flutter analyze` sin incidencias.
- Ensayo real PWA con Chromium, service worker, IndexedDB, API local y desconexión: todos los pasos aprobados. Se conserva en `frontend_marketplace_moda/scripts/qa/`, con servidor sintético en `tests/e2e/offline_server.py`.
- Primer recorrido: venta de 2 unidades y reserva de 1; queda una venta central y stock 17. Segundo recorrido: conflicto de una venta de 3, ajuste a 1 con stock central 1; quedan dos ventas y stock 0. Repetir la sincronización no duplica documentos.
- Los tres fallos iniciales de las pruebas de respaldo se debían a ejecutar sus temporales dentro del workspace, un destino que esas pruebas prohíben. Al usar temporales del sistema, las nueve pruebas de ese módulo pasan. No se generó ningún respaldo real.

## Uso y límites de lo validado

Con conexión, ingresar a la empresa y abrir **Sin conexión → Actualizar catálogo**. Después se puede abrir el catálogo, registrar reservas o **Registrar venta de contado**, cerrar la aplicación y consultar las operaciones locales al reabrir. Las descargas antiguas necesitan renovarse para recibir las cajas y la vigencia de precios.

La primera descarga y una identidad válida requieren conexión previa. La vigencia del precio para ventas es configurable (`OFFLINE_PRICE_VALIDITY_HOURS`, 24 horas por defecto); el catálogo puede seguir consultándose después con aviso. Las nuevas ventas locales usan el precio regular por variante de la descarga; la aplicación automática de ofertas en esas pantallas no queda certificada por este ensayo. Los ajustes de efectivo se registran para que el encargado gestione el reintegro correspondiente.

La reinstalación del navegador o el borrado manual de sus datos no equivalen a cerrar y reabrir: eliminan el almacenamiento del dispositivo. La sincronización en segundo plano de Android está implementada y probada con sus dependencias simuladas; su ejecución efectiva depende del sistema operativo y queda pendiente medirla en un teléfono físico. El APK producido es de depuración, no una publicación en una tienda de aplicaciones.

No hay migración nueva de PostgreSQL para estas correcciones. Los contratos del snapshot se amplían y se conserva el esquema local versión 2. No se ejecutaron semillas ni modificaciones manuales de la base de producción.
