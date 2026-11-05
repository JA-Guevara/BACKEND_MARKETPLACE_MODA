"""Pruebas unitarias para reglas puras de marca y contraste WCAG (RS-3)."""
import pytest
from src.plataforma_saas.domain.marca import (
    contraste,
    tinta_sobre,
    color_oscuro,
    enmascarar_cuenta,
    requisitos_publicacion,
    TenantSnapshot,
)


def test_contraste_extremos():
    c = contraste("#FFFFFF", "#000000")
    assert 20.5 <= c <= 21.5


def test_tinta_sobre():
    # Tono oscuro -> tinta blanca
    assert tinta_sobre("#74394E") == "#FFFFFF"
    # Tono claro -> tinta oscura
    assert tinta_sobre("#F2D16B") == "#1F1B1D"


def test_color_oscuro_contraste():
    # #1A1718 es el fondo oscuro de la app
    cand = color_oscuro("#74394E")
    assert contraste(cand, "#1A1718") >= 4.5


def test_enmascarar_cuenta():
    assert enmascarar_cuenta("1234567890") == "••••••7890"
    assert enmascarar_cuenta("4521") == "4521"
    assert enmascarar_cuenta("") == ""


def test_requisitos_publicacion():
    # Caso incompleto: sin logo y solo 1 prenda
    snap = TenantSnapshot(
        subscription_active=True,
        has_branch_with_hours=True,
        logo_url=None,
        active_products_with_photo_count=1,
        has_active_payment_method=True,
    )
    faltantes = requisitos_publicacion(snap)
    assert "logo" in faltantes
    assert "products_with_photo" in faltantes
    assert len(faltantes) == 2

    # Caso completo
    completo = TenantSnapshot(
        subscription_active=True,
        has_branch_with_hours=True,
        logo_url="https://res.cloudinary.com/demo/image/upload/logo.webp",
        active_products_with_photo_count=3,
        has_active_payment_method=True,
    )
    assert requisitos_publicacion(completo) == []
