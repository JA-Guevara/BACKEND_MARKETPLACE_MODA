"""Ilustraciones planas de prendas para el catálogo de demostración.

No descarga nada: dibuja cada prenda con Pillow a partir de su tipo y color, en
proporción 3:4 (la misma que usa `.product-image` en el frontend). Las imágenes
se guardan en `frontend_marketplace_moda/public/demo/`, así que el frontend las
sirve por ruta relativa tanto en local como en el despliegue.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ANCHO, ALTO = 900, 1200
FONDO = (243, 241, 235)


def _mezclar(color: tuple[int, int, int], hacia: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(round(c + (h - c) * factor) for c, h in zip(color, hacia))  # type: ignore[return-value]


def _rgb(hex_code: str) -> tuple[int, int, int]:
    valor = hex_code.lstrip('#')
    return tuple(int(valor[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _polera(d: ImageDraw.ImageDraw, tono, sombra, manga_larga: bool = False):
    hombro_y, bajo_y = 330, 900
    manga_y = 620 if manga_larga else 520
    d.polygon([(250, hombro_y), (450, 290), (650, hombro_y), (650, bajo_y), (250, bajo_y)], fill=tono)
    d.polygon([(250, hombro_y), (160, 430), (215, manga_y), (250, manga_y - 60)], fill=sombra)
    d.polygon([(650, hombro_y), (740, 430), (685, manga_y), (650, manga_y - 60)], fill=sombra)
    d.arc([395, 270, 505, 350], 0, 180, fill=_mezclar(tono, (0, 0, 0), 0.35), width=10)


def _camisa(d: ImageDraw.ImageDraw, tono, sombra):
    _polera(d, tono, sombra, manga_larga=True)
    d.polygon([(450, 300), (395, 285), (430, 400)], fill=_mezclar(tono, (255, 255, 255), 0.25))
    d.polygon([(450, 300), (505, 285), (470, 400)], fill=_mezclar(tono, (255, 255, 255), 0.25))
    d.line([(450, 350), (450, 900)], fill=_mezclar(tono, (0, 0, 0), 0.3), width=6)
    for y in range(430, 880, 90):
        d.ellipse([443, y, 457, y + 14], fill=_mezclar(tono, (255, 255, 255), 0.6))


def _blusa(d: ImageDraw.ImageDraw, tono, sombra):
    d.polygon([(270, 330), (450, 285), (630, 330), (670, 900), (230, 900)], fill=tono)
    d.polygon([(270, 330), (185, 450), (240, 600), (285, 560)], fill=sombra)
    d.polygon([(630, 330), (715, 450), (660, 600), (615, 560)], fill=sombra)
    d.polygon([(408, 290), (450, 420), (492, 290)], fill=FONDO)
    for x in range(300, 620, 80):
        d.line([(x, 700), (x + 20, 890)], fill=_mezclar(tono, (255, 255, 255), 0.3), width=5)


def _vestido(d: ImageDraw.ImageDraw, tono, sombra):
    d.polygon([(300, 320), (450, 280), (600, 320), (620, 620), (720, 1010), (180, 1010), (280, 620)], fill=tono)
    d.polygon([(300, 320), (225, 430), (270, 540), (305, 510)], fill=sombra)
    d.polygon([(600, 320), (675, 430), (630, 540), (595, 510)], fill=sombra)
    d.line([(285, 620), (615, 620)], fill=_mezclar(tono, (0, 0, 0), 0.25), width=10)


def _pantalon(d: ImageDraw.ImageDraw, tono, sombra, corto: bool = False):
    bajo = 780 if corto else 1050
    d.polygon([(310, 330), (590, 330), (585, 520), (450, 540), (315, 520)], fill=tono)
    d.polygon([(315, 520), (445, 540), (430, bajo), (320, bajo)], fill=tono)
    d.polygon([(585, 520), (455, 540), (470, bajo), (580, bajo)], fill=sombra)
    d.rectangle([310, 330, 590, 375], fill=_mezclar(tono, (0, 0, 0), 0.25))
    d.line([(450, 380), (450, 530)], fill=_mezclar(tono, (0, 0, 0), 0.3), width=5)


def _falda(d: ImageDraw.ImageDraw, tono, sombra):
    d.polygon([(330, 360), (570, 360), (680, 900), (220, 900)], fill=tono)
    d.rectangle([330, 360, 570, 405], fill=_mezclar(tono, (0, 0, 0), 0.25))
    for x in range(280, 640, 90):
        d.line([(x + 60, 420), (x, 890)], fill=sombra, width=6)


def _chaqueta(d: ImageDraw.ImageDraw, tono, sombra):
    d.polygon([(260, 330), (450, 290), (640, 330), (640, 920), (260, 920)], fill=tono)
    d.polygon([(260, 330), (165, 450), (220, 700), (265, 660)], fill=sombra)
    d.polygon([(640, 330), (735, 450), (680, 700), (635, 660)], fill=sombra)
    d.polygon([(450, 300), (350, 330), (420, 620), (450, 480)], fill=_mezclar(tono, (0, 0, 0), 0.2))
    d.polygon([(450, 300), (550, 330), (480, 620), (450, 480)], fill=_mezclar(tono, (0, 0, 0), 0.2))
    d.line([(450, 480), (450, 920)], fill=_mezclar(tono, (0, 0, 0), 0.35), width=7)


DIBUJOS = {
    'poleras': lambda d, t, s: _polera(d, t, s),
    'camisas': _camisa,
    'blusas': _blusa,
    'vestidos': _vestido,
    'pantalones': lambda d, t, s: _pantalon(d, t, s),
    'shorts': lambda d, t, s: _pantalon(d, t, s, corto=True),
    'faldas': _falda,
    'chaquetas': _chaqueta,
}


def generar(tipo: str, hex_color: str, destino: Path) -> Path:
    """Dibuja la prenda y devuelve la ruta del archivo WebP escrito."""
    lienzo = Image.new('RGB', (ANCHO, ALTO), FONDO)
    d = ImageDraw.Draw(lienzo)
    d.ellipse([120, 180, 780, 1080], fill=_mezclar(FONDO, (255, 255, 255), 0.7))
    tono = _rgb(hex_color)
    sombra = _mezclar(tono, (0, 0, 0), 0.18)
    DIBUJOS.get(tipo, DIBUJOS['poleras'])(d, tono, sombra)
    destino.parent.mkdir(parents=True, exist_ok=True)
    lienzo.save(destino, 'WEBP', quality=82, method=4)
    return destino
