# Corrección del probador virtual — 19 de septiembre de 2026

## Problema observado

La cámara y la silueta se mostraban, pero no la prenda de referencia. La acción administrativa que preparaba la foto omitía el color de la variante. El servicio requiere ese dato para crear un recurso por color, por lo que la solicitud fallaba y la vista caía en la silueta de respaldo.

## Corrección aplicada

- El formulario de producto permite elegir el color antes de usar **Preparar desde foto** y envía `color_id` al servicio.
- El mismo formulario presenta el estado y la vista previa transparente del recurso preparado para cada color.
- La sesión del probador solo superpone recursos `prepared_2_5d`. Las fotos comerciales antiguas o sin recorte ya no se dibujan como un rectángulo con fondo blanco sobre la cámara.
- El preparador conserva la transparencia existente de PNG/WebP. Para JPG, PNG con fondo o WebP sin alpha, detecta y recorta un fondo uniforme y genera WebP transparente.
- Si no puede separar la prenda con fiabilidad, el recurso queda fallido en vez de publicar una superposición incorrecta.

## Cómo preparar una prenda

1. Ingresar como administrador a **Catálogo** y abrir la prenda.
2. En **Probador virtual**, seleccionar el color que se probará.
3. Pulsar **Preparar desde foto**.
4. Confirmar que aparezca la miniatura sin fondo y el estado **Listo**.
5. Abrir la prenda como cliente, seleccionar el mismo color y usar **Probar en cámara**.

Cada color debe prepararse de forma independiente, porque puede tener una foto, tono o corte distinto.

## Requisitos de la imagen

No hace falta vectorizarla ni convertirla a SVG. Se necesita una imagen frontal de una sola prenda, preferentemente PNG o WebP con transparencia. También se aceptan fotos JPG con fondo liso que contraste con la prenda. Las fotos de una persona usando la prenda, varios objetos, fondos complejos o blanco sobre blanco no permiten un recorte confiable con este procesamiento local.

Este módulo es una superposición 2.5D guiada por landmarks del cuerpo: adapta posición y escala a la cámara, pero no crea un modelo 3D de la prenda.

## Validación realizada

- Pruebas unitarias del backend: 183 aprobadas.
- Pruebas del frontend: 303 aprobadas.
- Compilación de producción del frontend: aprobada.
- Validación SQL de migraciones hasta `0012_returns`: aprobada.

Para que el entorno publicado reciba la corrección, debe desplegarse el backend y frontend actuales y ejecutar las migraciones pendientes con `alembic upgrade head` en ese entorno.
