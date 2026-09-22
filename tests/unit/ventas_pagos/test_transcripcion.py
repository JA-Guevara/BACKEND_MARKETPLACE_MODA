"""Cuando el dictado devuelve algo que la persona no dijo.

Un modelo de voz a texto ante silencio no devuelve vacio: inventa una frase de
sus datos de entrenamiento. Si eso llega al asistente, responde a un mensaje
que nadie escribio y la accion real que se queria pedir nunca se ejecuta.
"""
import pytest

from src.ventas_pagos.domain.transcripcion import es_alucinacion, normalizar, texto_utilizable


class TestAlucinaciones:
    @pytest.mark.parametrize(
        "texto",
        [
            "Subtítulos realizados por la comunidad de Amara.org",
            "Subtitulos realizados por la comunidad de Amara.org",
            "subtítulos por la comunidad de amara.org",
            "Subtitulado por la comunidad de Amara.org",
            "¡Gracias por ver el video!",
            "Más información en www.amara.org",
            "Suscríbete al canal",
        ],
    )
    def test_descarta_lo_que_el_modelo_inventa_ante_silencio(self, texto):
        assert es_alucinacion(texto) is True
        assert texto_utilizable(texto) == ""

    @pytest.mark.parametrize(
        "texto",
        [
            "exportame un reporte en PDF",
            "Exportá el reporte de ventas del último mes en Excel",
            "mostrame las ventas por sucursal",
            "registrame una campera de cuero negra a 450 bolivianos",
            "si",
            "ok",
            "no",
        ],
    )
    def test_deja_pasar_una_indicacion_real(self, texto):
        assert es_alucinacion(texto) is False
        assert texto_utilizable(texto) == texto.strip()

    def test_una_sola_letra_no_es_una_indicacion(self):
        assert es_alucinacion("a") is True

    def test_el_vacio_y_los_espacios_se_descartan(self):
        assert es_alucinacion("") is True
        assert es_alucinacion("   ") is True
        assert texto_utilizable(None) == ""

    def test_tambien_descarta_la_instruccion_interna_repetida(self):
        # El modelo puede devolver el prompt del sistema en vez de transcribir.
        assert es_alucinacion("Conversación en español de FashionStore") is True

    def test_cualquier_variante_con_amara_se_descarta(self):
        # La frase cambia pero el dominio delata el origen.
        assert es_alucinacion("Subtítulos: Amara.org y colaboradores") is True


class TestNormalizacion:
    def test_ignora_acentos_mayusculas_y_espacios(self):
        assert normalizar("  SUBTÍTULOS   por  la COMUNIDAD ") == "subtitulos por la comunidad"

    def test_recorta_puntuacion_de_los_bordes(self):
        assert normalizar("¡Gracias por ver el video!") == "gracias por ver el video"

    def test_no_toca_la_puntuacion_del_medio(self):
        assert normalizar("amara.org") == "amara.org"


class TestLoQueSeEnvia:
    def test_una_indicacion_valida_conserva_acentos_y_mayusculas(self):
        # Se filtra para decidir, pero se envia el texto original: el asistente
        # necesita leer lo que la persona dijo, no una version normalizada.
        original = "Exportá el reporte de Ventas en PDF"
        assert texto_utilizable(original) == original
