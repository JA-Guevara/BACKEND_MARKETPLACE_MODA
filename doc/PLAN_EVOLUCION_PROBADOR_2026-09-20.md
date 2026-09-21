# Plan de evolución del probador virtual

## Objetivo

Convertir cualquier foto comercial razonable de una prenda en una experiencia útil para el cliente, sin mostrar rectángulos con fondo ni prometer una precisión física inexistente.

## Decisión de producto

Se ofrecen dos modos complementarios:

1. **Espejo en vivo**: cámara, pose corporal y prenda recortada que sigue hombros, torso o cadera. Responde de inmediato y se parece al probador con Kinect de referencia.
2. **Foto IA realista**: el cliente toma o sube una foto frontal; un servicio de virtual try-on genera una imagen final de la persona usando esa prenda. Es una imagen de resultado, no vídeo en tiempo real.

El modo actual 2.5D es la base del espejo. La foto IA es el modo de mayor fidelidad. Ambos deben convivir bajo una misma pantalla, con nombres claros y una indicación de qué representa cada uno.

## Por qué no generar un 3D desde una sola foto

Una foto frontal no contiene información fiable de espalda, laterales, grosor, patrón de costura ni caída de la tela. Un modelo 3D generado por IA puede verse atractivo al girar, pero inventará partes de la prenda y no mejorará el ajuste sobre el cuerpo. Para un 3D fiable se necesitarían fotos frontal, posterior y laterales, o el patrón/CAD del fabricante, además de simulación de tela.

Por eso el 3D queda como mejora futura para una vista giratoria del catálogo, no como requisito del probador.

## Flujo para cualquier imagen de catálogo

1. Al crear o editar una prenda, se asocia la imagen con un color y se detecta su tipo: superior, inferior, vestido, abrigo o accesorio.
2. Una tarea en segundo plano intenta obtener la silueta con un segmentador de imágenes especializado. Produce `transparent_url`, máscara, porcentaje de cobertura y una puntuación de calidad.
3. Si la puntuación es suficiente, se calculan anclajes y el recurso queda **Listo** para el espejo.
4. Si es dudosa, el administrador recibe un editor simple: pincel para conservar/quitar, recorte, tipo de prenda y anclajes. No se publica hasta confirmarlo.
5. Si la foto es de una persona, tiene varias prendas, el fondo tapa los bordes o la prenda es blanca sobre blanco, se informa el motivo y se solicita una foto de producto plana o con fondo contrastante.

Una imagen transparente PNG/WebP evita el paso de segmentación y se acepta directamente. No se requiere vectorizarla ni convertirla a SVG.

## Mejoras del espejo en vivo

- Conservar MediaPipe Pose para hombros, caderas y escala corporal.
- Añadir segmentación de persona para que los brazos y el cabello se dibujen delante de la prenda cuando corresponda; evita el efecto de prenda pegada encima de todo el cuerpo.
- Renderizar la prenda con WebGL/canvas y una malla deformable simple basada en hombros y caderas, en lugar de escalar solo un rectángulo.
- Estabilizar los landmarks para reducir saltos, ocultar la prenda cuando se pierde la pose y mostrar una guía de distancia y postura.
- Mantener ajustes manuales de tamaño, altura y giro, además de una opción de elegir talla.
- Permitir capturar una foto del resultado solo con consentimiento explícito y borrarla al terminar, salvo que el cliente decida guardarla.

## Foto IA realista

Entrada: una foto frontal de cuerpo completo del cliente, la foto de la prenda y su categoría.

Salida: una imagen generada de la persona usando la prenda, guardada temporalmente con estado `queued`, `processing`, `ready` o `failed`. La generación debe realizarse en segundo plano y no bloquea la cámara.

Una API especializada de virtual try-on puede resolver esta fase. FASHN, por ejemplo, recibe una imagen de persona y una de prenda y genera el resultado; su variante rápida está orientada a comercio y su variante de calidad a una imagen final. Antes de integrarla se deben evaluar costo por imagen, tiempos, política de eliminación y permiso explícito del cliente.

Alternativa sin proveedor: desplegar un modelo VTON en un servicio propio con GPU. Ofrece más control sobre imágenes y datos, pero exige infraestructura, observabilidad, colas y mantenimiento del modelo.

## Cambios técnicos propuestos

### Fase 1 — calidad de recursos del catálogo

- Sustituir el recorte por fondo liso por un segmentador IA y conservar el recorte actual como respaldo sin conexión.
- Crear `quality_score`, `quality_reason`, `source_image_url`, `preview_url` y `reviewed_by` en el recurso de probador.
- Ejecutar preparación masiva por producto y color; permitir reintento y revisión manual.
- Añadir pruebas con fondo blanco, fondo gris, prenda blanca, fondo complejo y foto de modelo.

### Fase 2 — espejo mejorado

- Incorporar máscara de persona y orden de capas frente/detrás.
- Aplicar malla de cuatro a ocho puntos a prendas superiores, inferiores y vestidos.
- Medir FPS, pérdida de pose y porcentaje de recursos correctamente preparados.

### Fase 3 — resultado IA

- Nuevo módulo `tryon_ai_jobs` con proveedor intercambiable, cola y estados.
- Endpoints: crear trabajo, consultar estado, cancelar y eliminar resultado.
- Límite por cliente, expiración de imágenes y auditoría sin almacenar la foto del cliente más tiempo del necesario.
- Botón: **Generar foto realista** junto a **Probar en cámara**.

## Criterios de aceptación

- Una foto PNG/WebP transparente se muestra en el espejo sin intervención.
- Una foto JPEG con fondo liso se prepara automáticamente y ofrece vista previa antes de publicarse.
- Una imagen difícil no aparece como rectángulo: se deriva a edición manual o se marca fallida con una razón clara.
- El espejo responde de forma fluida y alinea la prenda al mover hombros y torso.
- La foto IA informa que es una simulación visual y no confirma talla ni ajuste físico.
- Las imágenes de cámara del cliente se procesan solo con consentimiento y se eliminan según la política definida.
