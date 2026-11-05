import pytest

from scripts.respaldo import esquema, verificar_restauracion as verificar
from scripts.respaldo.respaldar import ErrorRespaldo


LOCAL = "postgresql://qa@127.0.0.1/ensayo"
LIMPIA = "postgresql://qa@127.0.0.1/limpia"


@pytest.mark.parametrize("url", ["postgresql://qa@db.example.invalid/ensayo",
    "postgresql://qa@localhost/ensayo?hostaddr=203.0.113.5",
    "postgresql://qa@localhost/ensayo?service=remoto",
    "postgresql://qa@localhost/host=remoto"])
def test_rechaza_destino_remoto_aun_con_override(monkeypatch, tmp_path, url):
    monkeypatch.setenv("ALLOW_REMOTE_DB", "1")
    monkeypatch.setattr(verificar, "consulta", lambda *a, **kw: pytest.fail("no debe intentar conexión"))
    with pytest.raises(ErrorRespaldo, match="local|redirecciones"):
        verificar.restaurar(tmp_path / "copia.dump", url)


def test_rechaza_base_con_datos_antes_de_pg_restore(monkeypatch, tmp_path):
    copia = tmp_path / "copia.dump"
    copia.write_bytes(b"PGDMP")
    monkeypatch.setattr(verificar, "consulta", lambda *a, **kw: "1")
    monkeypatch.setattr(verificar, "ejecutar", lambda *a, **kw: pytest.fail("no debe restaurar"))
    with pytest.raises(ErrorRespaldo, match="base local vacía"):
        verificar.restaurar(copia, LOCAL)


def test_reporte_falla_por_revision_distinta_permiso_desconocido_e_id_erroneo(monkeypatch):
    monkeypatch.setattr(verificar, "_revisiones", lambda *a: ["20261108_0028"])
    monkeypatch.setattr(verificar, "_consulta", lambda *a: "2")
    monkeypatch.setattr(verificar, "_permisos", lambda url:
                        {"users.read": "id-correcto"} if url == LIMPIA else
                        {"users.read": "id-erroneo", "secreto-que-no-se-publica": "otro-id"})
    checks = {check["name"]: check for check in verificar.comprobar(LOCAL, revision_esperada="20261109_0031", limpia=LIMPIA)}
    assert not checks["revision"]["ok"]
    assert checks["revision"]["details"]["actual"] == "20261108_0028"
    assert checks["tablas_clave"]["ok"]
    assert not checks["permisos"]["ok"]
    assert checks["permisos"]["details"] == {"expected": 1, "missing": 0, "extra": 1, "wrong_id": 1}
    assert "secreto-que-no-se-publica" not in repr(checks)


def test_revision_explicita_debe_ser_un_id_completo_en_la_cadena():
    assert verificar.revision_codigo("20261109_0031") == "20261109_0031"
    with pytest.raises(ErrorRespaldo, match="no existe"):
        verificar.revision_codigo("20261109")


def test_esquema_ignora_orden_de_columnas_sin_borrar_cambios_en_literales():
    original = """\\restrict abc
-- Name: item; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.item (
    id integer NOT NULL,
    name text DEFAULT 'dos  espacios'
);
\\unrestrict abc"""
    reordenado = """\\restrict xyz
-- Name: item; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.item (
    name text DEFAULT 'dos  espacios',
    id integer NOT NULL
);
\\unrestrict xyz"""
    assert esquema._sentencias(original) == esquema._sentencias(reordenado)
    assert esquema._sentencias(original) != esquema._sentencias(reordenado.replace("dos  espacios", "dos espacios"))
