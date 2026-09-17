"""Puntos de anclaje de la prenda, derivados de su silueta.

Un anclaje dice "esta parte de la imagen corresponde a esta parte del cuerpo".
El probador los empareja con los puntos corporales que devuelve la detección de
pose para ubicar, escalar y rotar la prenda.

No es inteligencia artificial: es geometría sobre la máscara ya segmentada. Se
declara así de explícito porque conviene distinguir qué resuelve un modelo y qué
resuelve un algoritmo determinista.

Todas las coordenadas son relativas (0..1) respecto de la imagen recortada, de
modo que sirven sin importar el tamaño final del recurso.
"""
from PIL import Image

# Regiones del cuerpo sobre las que puede trabajar el probador.
UPPER_BODY = "upper_body"
LOWER_BODY = "lower_body"
FULL_BODY = "full_body"
FEET = "feet"
REGIONES = {UPPER_BODY, LOWER_BODY, FULL_BODY, FEET}

# Altura relativa donde se mide cada anclaje dentro de la silueta.
_FILAS = {
    UPPER_BODY: {"shoulder": 0.10, "chest": 0.28, "hem": 0.96},
    LOWER_BODY: {"waist": 0.04, "hip": 0.28, "hem": 0.96},
    FULL_BODY: {"shoulder": 0.08, "waist": 0.42, "hem": 0.97},
    FEET: {"top": 0.10, "hem": 0.95},
}


# Un píxel cuenta como prenda por encima de este valor. El borde queda
# difuminado por el suavizado de la máscara, así que el umbral es bajo.
UMBRAL = 16
# Cada anclaje se mide sobre una banda de filas, no sobre una sola: una fila
# suelta puede caer en un hueco (entre las dos piernas de un short, por ejemplo)
# y devolver un par izquierda/derecha sin ancho real.
BANDA = 0.035
# Por debajo de este ancho relativo el par se descarta: un "hombro" de dos
# píxeles no sirve para escalar la prenda.
ANCHO_MINIMO = 0.08


def _fila_extremos(mascara: Image.Image, fila: int) -> tuple[float, float] | None:
    ancho, alto = mascara.size
    if not 0 <= fila < alto:
        return None
    pixeles = list(mascara.crop((0, fila, ancho, fila + 1)).getdata())
    visibles = [x for x, valor in enumerate(pixeles) if valor > UMBRAL]
    if not visibles:
        return None
    return visibles[0] / ancho, visibles[-1] / ancho


def _extremos(mascara: Image.Image, proporcion: float) -> tuple[float, float] | None:
    """Extensión de la silueta alrededor de esa altura relativa.

    Recorre una banda de filas y se queda con el borde más externo encontrado,
    que es lo que corresponde al ancho real de la prenda a esa altura.
    """
    _, alto = mascara.size
    inicio = max(0, int((proporcion - BANDA) * alto))
    final = min(alto - 1, int((proporcion + BANDA) * alto))
    izquierda, derecha = 1.0, 0.0
    for fila in range(inicio, final + 1):
        extremos = _fila_extremos(mascara, fila)
        if not extremos:
            continue
        izquierda = min(izquierda, extremos[0])
        derecha = max(derecha, extremos[1])
    if derecha - izquierda < ANCHO_MINIMO:
        return None
    return izquierda, derecha


def calcular_anclajes(mascara: Image.Image, body_region: str) -> dict:
    """Anclajes normalizados para la región indicada.

    Devuelve pares izquierda/derecha por cada altura relevante. Si una fila
    queda vacía (silueta irregular) se omite ese par: el probador usa los que
    haya y, si faltan, cae al ajuste manual.
    """
    if body_region not in REGIONES:
        body_region = UPPER_BODY
    ancho, alto = mascara.size
    anclajes: dict[str, list[float]] = {}
    for nombre, proporcion in _FILAS[body_region].items():
        extremos = _extremos(mascara, proporcion)
        if not extremos:
            continue
        izquierda, derecha = extremos
        anclajes[f"{nombre}_left"] = [round(izquierda, 4), round(proporcion, 4)]
        anclajes[f"{nombre}_right"] = [round(derecha, 4), round(proporcion, 4)]
    if not anclajes:
        # Silueta ilegible: se ancla al rectángulo completo para no dejar el
        # recurso sin referencia alguna.
        anclajes = {
            "shoulder_left": [0.0, 0.1],
            "shoulder_right": [1.0, 0.1],
            "hem_left": [0.0, 0.96],
            "hem_right": [1.0, 0.96],
        }
    anclajes["width_px"] = [float(ancho), float(alto)]
    return anclajes


def region_por_defecto(texto: str) -> str:
    """Región corporal deducida del nombre o categoría, como respaldo cuando no
    hay servicio de IA configurado."""
    referencia = (texto or "").lower()
    inferiores = ("pantal", "short", "bermuda", "falda", "jean", "jogger", "legging")
    completas = ("vestido", "enterizo", "mono", "overol", "jumpsuit")
    calzado = ("zapat", "calzado", "bota", "sandalia", "zapatilla", "tenis")
    if any(p in referencia for p in calzado):
        return FEET
    if any(p in referencia for p in completas):
        return FULL_BODY
    if any(p in referencia for p in inferiores):
        return LOWER_BODY
    return UPPER_BODY
