"""Cuándo lo que devolvió la transcripción no es lo que dijo la persona.

Los modelos de voz a texto **inventan** cuando el audio está en silencio o casi.
No devuelven vacío: devuelven una frase frecuente de sus datos de
entrenamiento. Como gran parte de ese material son vídeos subtitulados, lo que
sale es el crédito del subtítulo, y el más habitual en español es
«Subtítulos realizados por la comunidad de Amara.org».

Eso llega al asistente como si la persona lo hubiera dicho: se responde a un
mensaje que nadie escribió, y la acción real que quería pedir —exportar un
reporte, filtrar el tablero— nunca se ejecuta.

Acá se decide qué texto es basura del modelo. Es una función pura: se verifica
sin red, sin clave de API y sin micrófono.
"""
import unicodedata

#: Frases que el modelo devuelve ante silencio. Se comparan normalizadas.
ALUCINACIONES = (
    "subtitulos realizados por la comunidad de amara.org",
    "subtitulos por la comunidad de amara.org",
    "subtitulado por la comunidad de amara.org",
    "subtitulos creados por la comunidad de amara.org",
    "mas informacion en www.amara.org",
    "gracias por ver el video",
    "gracias por ver este video",
    "suscribete al canal",
    "no olvides suscribirte",
    "hasta la proxima",
)

#: Fragmentos que delatan una alucinación aunque la frase varíe.
SENALES = (
    "amara.org",
    # El modelo puede repetir la instrucción interna en vez de transcribir.
    "conversacion en espanol de fashionstore",
)

#: Una sola letra no es una indicación. Dos sí: si el asistente pregunta algo,
#: «sí», «no» y «ok» son respuestas válidas y no se pueden descartar.
MINIMO_CARACTERES = 2


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin espacios de más y sin puntuación de borde.

    Se compara así porque el modelo alterna «Subtítulos» y «Subtitulos», mete
    signos de admiración y cambia los espacios.
    """
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    limpio = " ".join(sin_acentos.casefold().split())
    return limpio.strip(" .,;:!¡?¿-–—\"'")


def es_alucinacion(texto: str) -> bool:
    """Si el texto es una invención del modelo y no algo que alguien dijo."""
    normalizado = normalizar(texto or "")
    if not normalizado:
        return True
    if len(normalizado) < MINIMO_CARACTERES:
        return True
    if normalizado in ALUCINACIONES:
        return True
    return any(senal in normalizado for senal in SENALES)


def texto_utilizable(texto: str) -> str:
    """El texto si sirve, o vacío si el modelo lo inventó."""
    return "" if es_alucinacion(texto) else (texto or "").strip()
