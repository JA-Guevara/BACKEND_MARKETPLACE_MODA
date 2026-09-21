"""Puntuación de calidad del recorte preparado.

Sin modelo de red neuronal: combina la cobertura de la foto, la proporción de
relleno dentro del recorte y la plausibilidad de las dimensiones para la región
del cuerpo. Es una heurística explícita y testeable, no una caja negra: si en el
futuro se integra un segmentador por IA, su salida alimenta estos mismos números.

La decisión de "qué se publica solo" sale de acá:
  - puntaje alto  -> ready, el probador lo puede usar.
  - puntaje dudoso -> review, no se publica hasta que el administrador confirma
    o descarta; mientras tanto el probador cae al dibujo, que siempre sirve.
  - segmentación fallida -> failed, con una razón clara.
"""
from PIL import Image

from src.probador_virtual.infrastructure.services import anclajes

# Por encima de este puntaje el recurso se publica solo; por debajo pide
# revisión. No es un umbral de "perfecto": es la línea entre confiable y dudoso.
UMBRAL_PUBLICAR = 60

# Umbral de opacidad para contar píxeles de silueta (igual que en anclajes).
UMBRAL = 16

# Rango razonable de relación ancho/alto de la silueta por región del cuerpo:
# una prenda superior es más alta que ancha, un zapato es ancho y bajo, etc.
# Fuera de estos rangos la silueta parece incompleta o de otro tipo de prenda.
_PROPORCIONES = {
    anclajes.UPPER_BODY: (0.5, 1.5),
    anclajes.LOWER_BODY: (0.6, 1.6),
    anclajes.FULL_BODY: (0.3, 0.9),
    anclajes.FEET: (1.0, 3.0),
}


def relleno_en_recorte(mascara: Image.Image) -> float:
    """Qué proporción de la caja recortada está ocupada por la silueta.

    Cerca de 1 significa un bloque prácticamente lleno (sospechoso de rectángulo
    con fondo); muy bajo significa una silueta quebrada en pedazos sueltos.
    """
    caja = mascara.point(lambda v: 255 if v > UMBRAL else 0).getbbox()
    if not caja:
        return 0.0
    ancho = caja[2] - caja[0]
    alto = caja[3] - caja[1]
    if ancho <= 0 or alto <= 0:
        return 0.0
    recorte = mascara.crop(caja)
    opacos = sum(1 for valor in recorte.getdata() if valor > UMBRAL)
    return opacos / float(ancho * alto)


def _proporcion_recorte(mascara: Image.Image) -> float | None:
    caja = mascara.point(lambda v: 255 if v > UMBRAL else 0).getbbox()
    if not caja:
        return None
    ancho = caja[2] - caja[0]
    alto = caja[3] - caja[1]
    if alto <= 0:
        return None
    return ancho / float(alto)


# Razones, en el idioma que ve el administrador en el panel.
RAZON_BUENA = "buena"
RAZON_FRAGMENTADA = "silueta_fragmentada"
RAZON_RECTANGULO = "recorte_casi_rectangulo"
RAZON_PROPORCION = "proporcion_atipica"
RAZON_COBERTURA = "cobertura_atipica"


def puntuar(mascara: Image.Image, cobertura: float, body_region: str) -> tuple[int, str]:
    """Devuelve (puntaje 0..100, razón) para la silueta ya segmentada.

    El puntaje es orientativo: la geometría sola no garantiza que la prenda esté
    completa. Por eso la frontera no es tajante y un resultado dudoso va a
    revisión en lugar de publicarse o descartarse a ciegas.
    """
    region = body_region if body_region in anclajes.REGIONES else anclajes.UPPER_BODY
    puntaje = 100
    razon = RAZON_BUENA

    # Cobertura respecto de la foto original: fuera de un rango creído la foto
    # trae de más (fondo enorme) o de menos (recorte perdido).
    if cobertura < 0.10:
        puntaje -= 20
        razon = razon if razon != RAZON_BUENA else RAZON_COBERTURA
    elif cobertura > 0.80:
        puntaje -= 25
        razon = razon if razon != RAZON_BUENA else RAZON_COBERTURA

    relleno = relleno_en_recorte(mascara)
    # Rectángulo lleno: el "recorte" volvió el bloque con fondo, no la silueta.
    if relleno > 0.99:
        puntaje -= 20
        razon = razon if razon != RAZON_BUENA else RAZON_RECTANGULO
    # Silueta quebrada: pedazos sueltos, imposible de anclar bien sobre el cuerpo.
    elif relleno < 0.35:
        puntaje -= 45
        razon = razon if razon != RAZON_BUENA else RAZON_FRAGMENTADA

    proporcion = _proporcion_recorte(mascara)
    if proporcion is not None:
        minimo, maximo = _PROPORCIONES[region]
        if not (minimo <= proporcion <= maximo):
            puntaje -= 25
            razon = razon if razon != RAZON_BUENA else RAZON_PROPORCION

    return max(0, min(100, puntaje)), razon