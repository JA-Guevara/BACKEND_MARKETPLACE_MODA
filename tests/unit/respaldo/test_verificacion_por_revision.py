"""Una copia válida no depende de que el checkout siga en su revisión."""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import re

from scripts.respaldo import verificar_restauracion as verificar


LOCAL = "postgresql://qa@127.0.0.1/ensayo"
LIMPIA = "postgresql://qa@127.0.0.1/referencia"
REVISION_PREVIA = "20261110_0032"


def test_copia_diaria_de_revision_previa_se_compara_con_su_propio_esquema(monkeypatch):
    referencias = []

    @contextmanager
    def referencia(url, revision):
        referencias.append(revision)
        yield LIMPIA

    monkeypatch.setattr(verificar, "_revisiones", lambda _: [REVISION_PREVIA])
    monkeypatch.setattr(verificar, "_consulta", lambda *_: "2")
    monkeypatch.setattr(verificar, "_permisos", lambda _: {"users.read": "id-estable"})
    monkeypatch.setattr(verificar, "_referencia", referencia)
    monkeypatch.setattr(verificar.esquema, "comparar", lambda actual, limpia: [])
    checks = verificar.comprobar(LOCAL)
    assert next(check for check in checks if check["name"] == "revision")["ok"]
    assert verificar.comparar_esquema(LOCAL) == []
    assert referencias == [REVISION_PREVIA, REVISION_PREVIA]


def test_revision_desconocida_falla_en_el_reporte_sin_restaurar(monkeypatch, tmp_path):
    dump = tmp_path / "copia.dump"
    dump.write_bytes(b"PGDMP")
    reporte = tmp_path / "reporte.json"
    monkeypatch.setenv("VERIFY_DATABASE_URL", LOCAL)
    monkeypatch.setattr(verificar, "revision_dump", lambda _: "revision_fuera_de_cadena", raising=False)
    monkeypatch.setattr(verificar, "restaurar", lambda *_: None)
    monkeypatch.setattr(verificar, "_revisiones", lambda _: ["revision_fuera_de_cadena"])
    @contextmanager
    def referencia(*_):
        yield LIMPIA
    monkeypatch.setattr(verificar, "_referencia", referencia)
    monkeypatch.setattr(verificar, "_consulta", lambda *_: "2")
    monkeypatch.setattr(verificar, "_permisos", lambda _: {"users.read": "id-estable"})
    monkeypatch.setattr(verificar.esquema, "comparar", lambda *_: [])
    result = verificar.main(["--archivo", str(dump), "--reporte", str(reporte)])
    assert result != 0
    content = json.loads(reporte.read_text(encoding="utf-8"))
    assert content["ok"] is False
    assert any(check["name"] == "revision" and check["ok"] is False
               and check["details"].get("code") == "verificacion_fallida" for check in content["checks"])


def test_workflow_pasa_revision_explicita_a_todos_los_tipos():
    path = Path(__file__).resolve().parents[3] / ".github/workflows/respaldo-bd.yml"
    workflow = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<<'PY'\n(.*?)\n\s*PY(?:\n|$)", workflow, re.S)
    matches = [script for script in scripts if "--revision-esperada" in script]
    assert len(matches) == 1
    import textwrap
    tree = ast.parse(textwrap.dedent(matches[0]))
    guarded = [node for node in ast.walk(tree) if isinstance(node, ast.If)
               and any(isinstance(child, ast.Constant) and child.value == "--revision-esperada"
                       for child in ast.walk(node))]
    assert not guarded, "La revisión de la copia debe pasarse siempre, no solo para pre_migration."
