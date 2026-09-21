# Control de calidad — probador virtual

Fecha: 20 de septiembre de 2026.

## Resultado

El flujo está integrado y compilado. El probador no publica una fotografía con fondo sin control de calidad: entrega una imagen transparente lista, una cola de revisión o el dibujo seguro de respaldo.

| Aspecto | Estado | Evidencia |
| --- | --- | --- |
| Recurso por producto y color | Aprobado | El recurso preparado se consulta por `product_id` y `color_id`; otro color no reutiliza su imagen. |
| Preparación y calidad | Aprobado | Puntaje 0–100, razón, estado `ready` / `review` / `failed`, miniatura y auditoría. |
| Revisión administrativa | Aprobado | Bandeja, aprobación, rechazo, reintento, ajuste de metadatos y preparación masiva. |
| Cámara y postura | Aprobado por pruebas de código | MediaPipe Pose alinea la superposición; si falla, ofrece ajuste manual y silueta con color. |
| Foto IA local | Aprobado | El proveedor `mock` permite probar el ciclo completo sin red. Se identifica como simulación. |
| Foto IA FASHN | Integración lista; requiere clave | Envía la foto y prenda como data URI, consulta el resultado, lo descarga al storage propio y registra errores visibles. |
| Privacidad | Aprobado | Consentimiento, límite de tres trabajos activos, cancelación, eliminación y expiración con borrado de archivos. |
| Migraciones | Aprobado | La generación SQL llega hasta `20260920_0014`. |

## Validación automatizada

- Backend de calidad, preparación y foto IA: **41 pruebas aprobadas**.
- Frontend completo: **320 pruebas aprobadas**.
- Compilación de producción del frontend: aprobada.

Las advertencias de Pillow indican una futura actualización de API de la librería; no fallan el comportamiento actual.

## Activación en servidor

1. Desplegar backend y frontend.
2. Ejecutar `alembic upgrade head`.
3. En el panel, abrir **Administración → Recursos del probador** y usar **Preparar pendientes en lote**.
4. Aprobar únicamente las prendas de la cola **Esperando revisión** cuya miniatura represente correctamente la prenda.
5. Para foto IA real: configurar `TRYON_PROVIDER=fashn` y `TRYON_API_KEY` en el servidor. Sin esa configuración el sistema informa que no hay proveedor, en vez de inventar una imagen.
6. Probar con navegador HTTPS y cámara física: aceptar el permiso, elegir un color preparado y verificar que el recurso siga hombros y torso.

## Límite conocido y criterio de uso

El recorte automático actual detecta fondos lisos y conserva PNG/WebP transparentes. Una foto de una persona, con fondo complejo o prenda blanca sobre blanco puede pasar a revisión o fallar; ese comportamiento es correcto porque impide una superposición falsa. La foto IA FASHN acepta fotos de prenda comunes para generar una imagen final, mientras que el espejo en vivo necesita el recurso transparente para mantenerse fluido.

El ajuste manual actual corrige región, tipo, anclajes y recurso habilitado. Un editor de pincel para corregir píxeles de la máscara sigue siendo una mejora futura; no se debe afirmar que está disponible.
