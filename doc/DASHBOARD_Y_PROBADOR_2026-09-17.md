# Coordinación con dashboard y probador — 17/09/2026

Esta tanda modifica presentación/frontend sin cambiar endpoints ni esquema de base de datos. Dashboard mantiene `/analytics/dashboard`, exportación múltiple y herramientas IA existentes. Ahora ofrece tres vistas, once gráficos y tablas explorables. 170 pruebas frontend y build aprobados; no se reejecutó backend por no haber cambios funcionales en él.

Diseño, límites y comprobaciones: `../../frontend_marketplace_moda/doc/DASHBOARD_Y_DECISION_PROBADOR_2026-09-17.md`.

Probador: no hay generación visual ni 3D nueva implementada. Se recomienda preservar cámara con superposición 2D y planificar generación foto-persona + prenda. Una futura integración necesita un puerto de proveedor, trabajos asincrónicos autorizados, límites de consumo y retención de imágenes. No reutilizar la clave del chat suponiendo que admite estas operaciones. No activar entrenamiento con fotos de clientes.

El modelo 3D generado desde una imagen puede servir para visor de catálogo, pero no resuelve deformación de ropa sobre cuerpos, oclusiones ni talla. Revisar una prueba representativa antes de ampliar el contrato. Las tareas de conciliación Stripe de la tanda anterior siguen documentadas por separado y pendientes de verificación publicada.
