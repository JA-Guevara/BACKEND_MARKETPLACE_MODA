from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

from scripts import railway_entrypoint as entry
from src.infrastructure.config.settings import settings

HEAD = "20261110_0032"
PREVIOUS = "20261109_0031"


@pytest.fixture
def gate(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": PREVIOUS})

    monkeypatch.setattr(settings, "database_url", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(entry, "create_engine", lambda url: engine)
    dispose = engine.dispose
    monkeypatch.setattr(engine, "dispose", Mock())
    monkeypatch.setattr(entry.ScriptDirectory, "from_config", lambda _: SimpleNamespace(get_current_head=lambda: HEAD))
    monkeypatch.setattr(entry, "_bloquear_migraciones", Mock())
    monkeypatch.delenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)

    def upgrade(config, target):
        assert target == "head"
        connection = config.attributes["connection"]
        assert entry._bloquear_migraciones.call_args.args == (connection,)
        connection.execute(text("UPDATE alembic_version SET version_num = :revision"), {"revision": HEAD})

    upgrade_mock = Mock(side_effect=upgrade)
    monkeypatch.setattr(entry.command, "upgrade", upgrade_mock)
    yield engine, upgrade_mock
    dispose()


def _revision(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def test_sin_pendientes_no_migra_ni_requiere_tabla_de_respaldos(gate):
    engine, upgrade = gate
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :revision"), {"revision": HEAD})
    entry.preparar()
    upgrade.assert_not_called()


def test_migra_sin_tabla_de_respaldos_ni_fecha_y_no_repite(gate):
    engine, upgrade = gate
    entry.preparar()
    entry.preparar()
    upgrade.assert_called_once()
    assert _revision(engine) == HEAD


def test_fallo_de_migracion_revierte_el_cambio_de_revision(gate):
    engine, upgrade = gate
    aplicar = upgrade.side_effect

    def aplicar_y_fallar(config, target):
        aplicar(config, target)
        raise RuntimeError("falló migración")

    upgrade.side_effect = aplicar_y_fallar
    with pytest.raises(RuntimeError, match="falló migración"):
        entry.preparar()
    upgrade.assert_called_once()
    assert _revision(engine) == PREVIOUS


def test_prepare_usa_dueno_sin_cambiar_conexion_de_la_aplicacion(gate, monkeypatch):
    engine, upgrade = gate
    application_url = "postgresql://fashionstore_app@127.0.0.1/qa"
    migration_url = "postgresql://migration_owner@127.0.0.1/qa"
    monkeypatch.setattr(settings, "database_url", application_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_url)
    selected = []
    monkeypatch.setattr(entry, "create_engine", lambda url: selected.append(url) or engine)
    entry.preparar()
    assert selected == [migration_url]
    assert settings.database_url == application_url
    upgrade.assert_called_once()


def test_prepare_rechaza_migrar_otra_base_antes_de_conectar(gate, monkeypatch):
    _, upgrade = gate
    monkeypatch.setattr(settings, "database_url", "postgresql://fashionstore_app@127.0.0.1/qa")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://migration_owner@127.0.0.1/otra")
    connect = Mock()
    monkeypatch.setattr(entry, "create_engine", connect)
    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL y DATABASE_URL"):
        entry.preparar()
    connect.assert_not_called()
    upgrade.assert_not_called()


def test_roles_de_pooler_y_host_directo_deben_ser_del_mismo_proyecto():
    direct = entry._database_identity("postgresql://postgres@db.proyecto-qa.supabase.co/postgres")
    pooler = entry._database_identity("postgresql://fashionstore_app.proyecto-qa@aws-0.region.pooler.supabase.com/postgres")
    other = entry._database_identity("postgresql://fashionstore_app.otro@aws-0.region.pooler.supabase.com/postgres")
    assert direct == pooler
    assert direct != other



@pytest.mark.parametrize("query", ["dbname=otra", "user=otro", "port=6432"])
def test_identidad_de_base_rechaza_overrides_libpq(query):
    with pytest.raises(ValueError, match="Destino ambiguo"):
        entry._database_identity("postgresql://app@127.0.0.1/qa?" + query)
