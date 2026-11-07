# Copias de negocio por empresa

Cada empresa puede solicitar un archivo manual, programar una copia diaria o semanal, consultar el historial y descargar solo sus copias verificadas. La plataforma tiene el mismo control en Empresa 360, sujeto a `platform.ops.read/write`. El acceso de empresa requiere `tenant.data_export`.

El trabajador persistente reclama trabajos con bloqueo y una concesión temporal; recupera interrupciones y evita ejecuciones dobles entre procesos. Toma una instantánea PostgreSQL `REPEATABLE READ READ ONLY`, comprueba todas las relaciones y restaura el paquete en una base SQLite aislada antes de marcarlo como verificado. El ensayo no certifica una recuperación de toda la instancia PostgreSQL.

Incluye catálogo, imágenes propias disponibles, marca, medios manuales de cobro, sucursales, inventario, operaciones comerciales, reservas, cambios, devoluciones, sincronización y referencias de usuarios y permisos. Excluye contraseñas y sesiones, claves de integración, contratos de la plataforma y modelos regenerables. Las imágenes externas permanecen como referencias. Los usuarios restaurados quedan inactivos.

## Activación

1. Ejecutar `python -m scripts.generar_clave_copias_empresa` en una sesión privada. El archivo se crea fuera de los tres repositorios en `_privado_bd/tenant-backup-encryption.env`; nunca imprime la clave.
2. Configurar `TENANT_BACKUP_ENCRYPTION_KEY` en Railway con el valor del archivo. Conservar la clave en custodia externa. Perderla impide recuperar los archivos cifrados; no sustituirla para resolver errores de configuración.
3. Reiniciar el servicio y comprobar que la pantalla indica que la custodia está configurada. `TENANT_BACKUP_WORKER_ENABLED` permite detener el trabajador. La programación viene desactivada hasta que el administrador la habilita.
4. Solicitar una copia con autorización del dueño, esperar su ensayo y descargar el ZIP. No se generó ninguna copia real de producción durante esta implementación.

Los archivos cifrados se guardan en BYTEA de PostgreSQL: sobreviven a un redespliegue, pero una pérdida total de la base también los afecta. Descargar una copia a custodia externa es necesario para protegerse de ese escenario. Esto no sustituye el respaldo global de infraestructura.

## Límites e importación

Retención configurable de 1–14 archivos verificados; no elimina la última copia válida por un fallo nuevo. Máximo 2 trabajos simultáneos por empresa y 12 solicitudes diarias. El límite por archivo viene de `TENANT_BACKUP_MAX_MB` (10 MB por defecto); falla explícitamente si falta una imagen propia, hay referencias cruzadas o se superan 50.000 filas.

El manifiesto incluye huella de estructura, cantidades y SHA-256. El importador requiere la misma versión de estructura y una base SQLite local vacía. Nunca restaura sobre una empresa activa ni ejecuta SQL aportado por el archivo:

```powershell
python -m scripts.restaurar_empresa_local --archivo "C:/ruta/copia.zip" --destino "sqlite+pysqlite:///C:/ruta/ensayo-vacio.db"
```

El ZIP conserva las imágenes en `images/`; el ensayo no las publica. Una recuperación sobre PostgreSQL requiere un procedimiento controlado de migración y revisión de identidades, fuera de este importador.
