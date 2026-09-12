# Estado del módulo comercial — 12/09/2026

Routers commerce/analytics registrados; migración 0003 presente. Frontend ya conecta carrito, pedidos propios, administración de pagos/pedidos y stock. Ver `../../frontend_marketplace_moda/doc/COMERCIO.md` para rutas de pantalla y pasos de uso.

## Pruebas

`.venv/Scripts/python.exe -m pytest tests/test_commerce_contract.py -q -p no:cacheprovider`: 2 pruebas aprobadas. Ejecuta rutas HTTP con SQLite descartable y sin pagos de red. Cubre propiedad de pedidos, permisos, stock, pago manual, estados, cancelación, duplicados y Stripe simulado; firma inválida probada por separado.

Se corrigió el carrito con prendas desactivadas: muestra disponibilidad cero y permite quitarlas, mientras crear pedido vuelve a validar cada variante en servidor.

## Migraciones

- Generación SQL PostgreSQL con `alembic upgrade head --sql`: aprobada, incluyendo tablas comerciales.
- Intento de ejecutar toda la cadena sobre SQLite temporal: falló por JSONB de la migración inicial de auditoría. No constituye un fallo de la nueva tabla comercial ni prueba de ejecución exitosa PostgreSQL.
- Pendiente ejecutar upgrade/downgrade en PostgreSQL descartable y probar concurrencia. No se tocaron datos reales.

## Configuración y limitaciones

STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET permanecen configurables; solo modo prueba. FRONTEND_URL determina retorno a `/mi-cuenta/pedidos`. AI_API_KEY es opcional. No poner claves privadas en frontend.

Pendiente conciliación de pagos, expiración de pedidos manuales, reembolsos, logística externa y movimientos completos de inventario. La confirmación por webhook es distinta del retorno del navegador.
