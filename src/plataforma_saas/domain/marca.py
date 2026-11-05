"""Reglas puras de marca, contraste WCAG y publicación de tienda (RS-3)."""
from dataclasses import dataclass
import re

HEX_REGEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
BG_DARK = "#1A1718"
INK_LIGHT = "#FFFFFF"
INK_DARK = "#1F1B1D"


def _hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    h = hex_code.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Color hexadecimal inválido: {hex_code}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def _luminancia_relativa(r: int, g: int, b: int) -> float:
    def canal(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(hex_a: str, hex_b: str) -> float:
    """Calcula el ratio de contraste WCAG 2.1 entre dos colores (1 a 21)."""
    l1 = _luminancia_relativa(*_hex_to_rgb(hex_a))
    l2 = _luminancia_relativa(*_hex_to_rgb(hex_b))
    mas_claro = max(l1, l2)
    mas_oscuro = min(l1, l2)
    return round((mas_claro + 0.05) / (mas_oscuro + 0.05), 2)


def tinta_sobre(hex_color: str) -> str:
    """Devuelve #FFFFFF o #1F1B1D según cuál ofrezca mayor contraste."""
    c_blanco = contraste(hex_color, INK_LIGHT)
    c_oscuro = contraste(hex_color, INK_DARK)
    return INK_LIGHT if c_blanco >= c_oscuro else INK_DARK


def color_oscuro(hex_color: str) -> str:
    """Aclara el color para tema oscuro hasta que el contraste con #1A1718 sea >= 4.5."""
    if contraste(hex_color, BG_DARK) >= 4.5:
        return hex_color.upper()

    r, g, b = _hex_to_rgb(hex_color)
    # Aclarar progresivamente mezclando con blanco
    for step in range(1, 101):
        factor = step / 100.0
        nr = int(r + (255 - r) * factor)
        ng = int(g + (255 - g) * factor)
        nb = int(b + (255 - b) * factor)
        cand = _rgb_to_hex(nr, ng, nb)
        if contraste(cand, BG_DARK) >= 4.5:
            return cand
    return "#FFFFFF"


def enmascarar_cuenta(numero: str) -> str:
    """Enmascara un número de cuenta mostrando solo los últimos 4 dígitos."""
    if not numero:
        return ""
    if len(numero) <= 4:
        return numero
    return "•" * (len(numero) - 4) + numero[-4:]


@dataclass
class TenantSnapshot:
    subscription_active: bool = False
    has_branch_with_hours: bool = False
    logo_url: str | None = None
    active_products_with_photo_count: int = 0
    has_active_payment_method: bool = False


def requisitos_publicacion(t: TenantSnapshot) -> list[str]:
    """Evalúa los 5 requisitos para publicar una tienda en el directorio."""
    faltantes: list[str] = []
    if not t.subscription_active:
        faltantes.append("subscription_active")
    if not t.has_branch_with_hours:
        faltantes.append("branch_with_hours")
    if not t.logo_url:
        faltantes.append("logo")
    if t.active_products_with_photo_count < 3:
        faltantes.append("products_with_photo")
    if not t.has_active_payment_method:
        faltantes.append("payment_method")
    return faltantes
