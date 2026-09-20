"""Separa la prenda del fondo de la foto de catálogo y describe su geometría.

La foto comercial del producto trae fondo liso (blanco o gris de estudio). Al
superponerla tal cual sobre la cámara se veía el rectángulo completo de la
fotografía: ese es el defecto que este módulo corrige, dejando el fondo
transparente y recortando al contorno de la prenda.

Trabaja solo con Pillow, sin numpy ni modelos de segmentación pesados: para
fondos lisos un relleno por difusión desde los bordes es suficiente y evita
sumar cientos de megabytes de dependencias al despliegue. Si en el futuro se
quiere una segmentación por red neuronal, reemplazar `recortar_fondo` sin tocar
el resto del flujo.
"""
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

# Color centinela para marcar el fondo durante el relleno. Se elige uno que no
# aparece en fotografía de ropa y se verifica antes de usarlo.
CENTINELA = (255, 0, 255)
# Tolerancia del relleno: cuánto puede variar el fondo (sombras, degradado).
TOLERANCIA = 38
# NOTA MEDIDA, no teorica: se probo bajar la tolerancia cuando el recorte falla
# (38 -> 24 -> 16 ...) y tambien un relleno que compara contra el pixel VECINO en
# vez de contra la esquina. Ninguna de las dos sirve cuando la prenda es del
# mismo color que su fondo: en el catalogo actual las prendas «blanco hueso»
# difieren del fondo en 4 sobre 255. Bajar la tolerancia deja la prenda DENTRO
# de un bloque de fondo y ese recorte pasaba por bueno, que es peor que fallar.
# Por eso se conserva una sola tolerancia y esos casos se marcan como no
# logrados: el probador cae al dibujo, que siempre funciona.
# Debajo de esta proporción de píxeles opacos se considera que la segmentación
# falló (por ejemplo, fondo con estampado que se comió toda la prenda).
MINIMO_PRENDA = 0.04
MAXIMO_PRENDA = 0.97


@dataclass
class PrendaRecortada:
    """Resultado de separar la prenda del fondo."""

    imagen: Image.Image
    """Prenda en RGBA, recortada a su contorno, con fondo transparente."""
    mascara: Image.Image
    """Máscara en escala de grises del mismo tamaño que `imagen`."""
    cobertura: float
    """Proporción de la foto original ocupada por la prenda."""
    logrado: bool = True
    """Si se pudo separar la prenda del fondo.

    En `False` la imagen es la foto original **con** su fondo: sirve para que el
    administrador vea qué pasó, pero no se puede mostrar sobre la cámara. Quien
    prepara el recurso debe marcarlo como fallido, no como listo.
    """
    tolerancia: int = TOLERANCIA
    """Tolerancia con la que se logró el recorte, para diagnóstico."""


def _fondo_probable(imagen: Image.Image) -> tuple[int, int, int]:
    """Color de fondo estimado a partir de las cuatro esquinas."""
    ancho, alto = imagen.size
    esquinas = [(0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)]
    pixeles = [imagen.getpixel(p) for p in esquinas]
    return tuple(sum(canal) // len(pixeles) for canal in zip(*pixeles))  # type: ignore[return-value]


def _centinela_libre(imagen: Image.Image) -> tuple[int, int, int]:
    """Devuelve un color que no exista en la imagen, para marcar el fondo."""
    colores = {color for _, color in imagen.getcolors(maxcolors=1 << 24) or []}
    for candidato in (CENTINELA, (0, 255, 255), (255, 255, 0), (1, 254, 3)):
        if candidato not in colores:
            return candidato
    return CENTINELA


def _intento(imagen: Image.Image, centinela, tolerancia: int) -> tuple[Image.Image, float]:
    """Marca el fondo con una tolerancia dada y devuelve la máscara y su cobertura."""
    ancho, alto = imagen.size
    lienzo = imagen.copy()
    # El fondo se propaga desde las cuatro esquinas: así un fondo liso se marca
    # completo aunque la prenda toque un borde.
    for punto in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)):
        ImageDraw.floodfill(lienzo, punto, centinela, thresh=tolerancia)

    # Máscara: 255 donde quedó prenda, 0 donde se marcó fondo.
    mascara = Image.new("L", (ancho, alto), 255)
    mascara.putdata([0 if pixel == centinela else 255 for pixel in lienzo.getdata()])
    opacos = sum(1 for valor in mascara.getdata() if valor)
    return mascara, opacos / float(ancho * alto)


def recortar_fondo(datos: bytes) -> PrendaRecortada:
    """Deja la prenda sobre fondo transparente, recortada a su contorno."""
    with Image.open(BytesIO(datos)) as original:
        original.load()
        # Si el administrador ya subió PNG/WebP con alfa, ese recorte es más
        # fiable que inferir nuevamente el fondo. Antes se convertía a RGB y
        # se perdía esa transparencia, por lo que un recurso correctamente
        # preparado volvía a aparecer con un rectángulo blanco.
        if "A" in original.getbands():
            preparada = original.convert("RGBA")
            mascara_existente = preparada.getchannel("A")
            ancho, alto = preparada.size
            opacos = sum(1 for valor in mascara_existente.getdata() if valor > 8)
            cobertura_existente = opacos / float(ancho * alto)
            caja_existente = mascara_existente.point(lambda v: 255 if v > 8 else 0).getbbox()
            if caja_existente and MINIMO_PRENDA <= cobertura_existente <= MAXIMO_PRENDA:
                return PrendaRecortada(
                    imagen=preparada.crop(caja_existente),
                    mascara=mascara_existente.crop(caja_existente),
                    cobertura=cobertura_existente,
                    logrado=True,
                    tolerancia=0,
                )
        imagen = original.convert("RGB")

    ancho, alto = imagen.size
    centinela = _centinela_libre(imagen)

    candidata, proporcion = _intento(imagen, centinela, TOLERANCIA)
    logrado = MINIMO_PRENDA <= proporcion <= MAXIMO_PRENDA
    mascara = candidata if logrado else None
    cobertura = proporcion if logrado else 0.0
    usada = TOLERANCIA
    if not logrado:
        # Ninguna tolerancia dejó una silueta creíble: fondo con estampado, o
        # foto sobre un modelo. Se devuelve la foto completa para que el
        # administrador vea qué pasó, pero marcada como no lograda: mostrarla
        # sobre la cámara sería el rectángulo con fondo que este módulo evita.
        mascara = Image.new("L", (ancho, alto), 255)
        cobertura = 1.0
    else:
        # Apertura: borra las motas sueltas que quedan del borde del fondo.
        mascara = mascara.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        # Cierre: tapa agujeros de un píxel dentro de la prenda.
        mascara = mascara.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        # Contrae un píxel: el contorno de la foto mezcla prenda y fondo, y sin
        # esto queda un halo claro alrededor de la silueta sobre la cámara.
        mascara = mascara.filter(ImageFilter.MinFilter(3))
        mascara = mascara.filter(ImageFilter.GaussianBlur(0.9))

    prenda = imagen.convert("RGBA")
    prenda.putalpha(mascara)
    caja = mascara.point(lambda v: 255 if v > 8 else 0).getbbox()
    if caja:
        prenda = prenda.crop(caja)
        mascara = mascara.crop(caja)
    return PrendaRecortada(
        imagen=prenda, mascara=mascara, cobertura=cobertura, logrado=logrado, tolerancia=usada
    )


def a_webp(imagen: Image.Image) -> bytes:
    """Serializa conservando el canal alfa."""
    salida = BytesIO()
    imagen.save(salida, "WEBP", quality=90, method=4, lossless=False, exact=True)
    return salida.getvalue()


def a_png_mascara(mascara: Image.Image) -> bytes:
    salida = BytesIO()
    mascara.save(salida, "PNG", optimize=True)
    return salida.getvalue()
