# Runbook de Despliegue y Operaciones · FashionStore SaaS

- **Proyecto:** FashionStore SaaS Multi-Tenant
- **Versión:** 2.0 (Segundo Parcial)
- **Cabeza Alembic Oficial:** `20261109_0031` (cadena única y lineal; repara el sello fantasma de producción)
- **Plataforma de Despliegue:** Railway (Backend + PostgreSQL) / Vercel o Netlify (Frontend PWA)

---

## 1. Principios de Seguridad y Aislamiento

> [!IMPORTANT]
> **REGLA DE ORO DE PRODUCCIÓN**: Cualquier comando que afecte la base de datos o el código en producción requiere la confirmación explícita y documentada del usuario.

- Nunca hardcodear contraseñas, secretos, tokens o cadenas de conexión en el repositorio o en la documentación.
- Todo acceso a base de datos de producción utiliza variables de entorno inyectadas por la plataforma de hosting.
- `railway.json` ejecuta `python -m alembic upgrade head` en `preDeployCommand`: **un merge a la rama desplegada ejecuta automáticamente las migraciones en producción**.

---

## 2. Variables de Entorno Requeridas (por Nombre)

### Backend (Railway / Producción)
- `DATABASE_URL`: Cadena de conexión PostgreSQL (con pooler o directa IPv4).
- `ALLOW_REMOTE_DB=1`: autorización explícita de conexión remota para el servicio Railway. Sin ella, el motor y Alembic rechazan hosts remotos. No definirla en desarrollo local. Configurarla únicamente dentro de la ventana de liberación autorizada; cambiar variables del servicio puede provocar un redespliegue.
- `JWT_SECRET_KEY`: Llave para la firma y verificación de tokens HS256 / RFC 8693.
- `AI_API_KEY`: Credencial del proveedor LLM (Gemini / OpenAI compatible).
- `AI_MODEL`: Modelo utilizado para generación de reportes y NL2SQL (`gemini-2.5-flash` o equivalente).
- `AI_TRANSCRIPTION_MODEL`: Modelo para dictado y transcripción de voz (`whisper-1` o equivalente).
- `PUBLIC_API_URL`: URL base pública del backend para generación de callbacks y links.
- `FRONTEND_URL`: URL base de la aplicación Angular PWA para CORS.
- `CORS_ORIGINS`: Lista de orígenes autorizados separados por coma.
- `OFFLINE_PRICE_VALIDITY_HOURS`: Ventana de validez para precios offline en instantáneas (ej. `24`).
- `DEFAULT_TENANT_SLUG`: Tenant por defecto para tiendas públicas no calificadas (`urbano`).
- `MEDIA_STORAGE_DIR`: Directorio de persistencia para archivos de medios y assets.
- `MEDIA_PUBLIC_BASE_URL`: URL pública para resolución de imágenes y comprobantes.

---

## 3. Orden de Integración y Cadena de Migraciones Alembic

La cadena de revisiones Alembic es estrictamente lineal para garantizar cero bifurcaciones (`alembic heads` muestra una única cabeza):

| Orden | Revisión | Identificador | Propósito |
|---|---|---|---|
| 1 | `20261029_0018` | Base | Cimientos base y administradores |
| 2 | `20261105_0019` | RS Ola 0 | Diccionario de permisos y roles de plataforma |
| 3 | `20261105_0020` | RS Ola 0 | Catálogo de módulos y permisos de módulo |
| 4 | `20261105_0021` | RS Ola 0 | Sesiones de soporte temporal (RFC 8693) |
| 5 | `20261104_0029` | RS-2 | Consola de plataforma, cuotas y sandbox |
| 6 | `20261104_0030` | RS-3 | Tienda pública, metadatos de marca y temas |
| 7 | `20261106_0022` | CU-06 | Ventas offline, folios provisionales |
| 8 | `20261106_0023` | CU-07 | Sincronización en lote (`sync_batches`, `sync_operations`, `sync_conflicts`) |
| 9 | `20261107_0024` | CU-10 | Modelos analíticos y entrenamiento ML (`ml_models`, `ml_predictions`) |
| 10 | `20261107_0025` | CU-08 | Cambios de prendas dentro de política de días (`garment_exchanges`) |
| 11 | `20261108_0026` | CU-09 | Consultas asistidas por IA y catálogo (`report_requests`) |
| 12 | `20261108_0027` | CU-11 | Motor de ofertas, descuentos y cupones (`commerce_promotions`) |
| 13 | `20261108_0028` | CU-12 | Registro de dispositivos offline y auditoría (`registered_devices`) |
| 14 | `20261109_0031` (HEAD) | Cierre | Reconcilia el esquema de producción: completa tablas/columnas/permisos faltantes, corrige índices y elimina la tabla temporal vacía `_rs_catalog_copies` |

> [!IMPORTANT]
> Producción quedó sellada con `20261108_0030`, una revisión que **no existe** en el repositorio, y con un esquema mixto. Antes de un `alembic upgrade head` normal hay que ejecutar `python scripts/reconciliar_produccion.py --aplicar --backup-archivo <respaldo>`. El script corrige el sello a `20261108_0028` y aplica `20261109_0031` en una sola transacción. Sin ese paso, `alembic current` falla con `Can't locate revision identified by '20261108_0030'`.

**Puerta vigente (05/11):** solo están autorizados el respaldo y el ensayo local. El respaldo debe generarse con `pg_dump -Fc -n public --no-owner --no-privileges` usando el pooler de sesión (5432), guardarse fuera de los repositorios y validarse con `pg_restore --list`. El runner exige tabla y datos de `public.alembic_version` y una antigüedad menor a 24 horas (`PG_RESTORE` permite indicar el ejecutable). Después de restaurar y reconciliar una copia local, deben coincidir su esquema y sus datos de referencia con el camino limpio. Solo entonces solicitar una confirmación conjunta para reconciliar producción, consolidar `main`, hacer push y desplegar. No reiniciar el servicio mientras siga el sello fantasma.

Si se vuelve al código anterior tras confirmar `0031`, restaurar primero el respaldo bajo una ventana de recuperación autorizada. El código anterior no reconoce esa revisión. La restauración descarta escrituras posteriores al respaldo.

---

## 4. Procedimiento de Despliegue Paso a Paso

### Fase 1: Pre-despliegue y Congelamiento
1. Ejecutar suites completas de pruebas unitarias y de integración localmente:
   ```powershell
   cd backend_marketplace_moda
   .venv\Scripts\python.exe -m pytest tests/unit
   ```
2. Verificar que Alembic no tenga cabezas múltiples:
   ```powershell
   .venv\Scripts\alembic.exe heads
   ```
   *Debe retornar exactamente: `20261109_0031 (head)`.*

### Fase 2: Respaldo de Producción y Ensayo en QA
3. ⛔ **RESPALDO DE BASE DE DATOS (Requiere confirmación explícita)**:
   ```bash
   pg_dump "$DATABASE_URL" -Fc -f "respaldo_pre_despliegue_$(date +%Y%m%d_%H%M%S).dump"
   ```
4. Restauración de prueba en entorno QA (`TEST_DATABASE_URL`):
   ```bash
   pg_restore -d "$TEST_DATABASE_URL" --clean "respaldo_pre_despliegue_*.dump"
   ```
5. Ejecutar migraciones en QA:
   ```bash
   alembic upgrade head
   ```

### Fase 3: Despliegue en Producción
6. ⛔ **MERGE A RAMA PRINCIPAL / DESPLEGADA (Requiere confirmación explícita)**:
   - Push a la rama conectada a Railway.
   - Railway detecta el commit y ejecuta `preDeployCommand: python -m alembic upgrade head`.
   - Railway levanta FastAPI con `uvicorn src.main:app`.
7. ⛔ **SIEMBRA DE DATOS DE DEMOSTRACIÓN (Requiere confirmación explícita)**:
   ```bash
   python -m scripts.seed_defensa
   ```
   *Siembra empresas "Urbano Boutique" (Profesional) y "Moda Cruceña" (Básico).*

### Fase 4: Verificación Post-Despliegue (Smoke Test)
8. Ejecutar script de verificación:
   ```powershell
   python -m scripts.verificar_despliegue --base-url "$PUBLIC_API_URL"
   ```
   *Debe reportar 100% de verificaciones aprobadas (`[PASS]`).*

---

## 5. Procedimiento de Reversión (Rollback)

Si el verificador reporta fallas críticas o el smoke test no concluye satisfactoriamente:
1. Revertir despliegue en Railway seleccionando el despliegue previo en el dashboard.
2. Si las migraciones generaron inconsistencias de esquema:
   ```bash
   # Restaurar dump tomado en Fase 2
   pg_restore -d "$DATABASE_URL" --clean "respaldo_pre_despliegue_*.dump"
   ```
3. Notificar inmediatamente al equipo y consultar `logs/` de Railway.
