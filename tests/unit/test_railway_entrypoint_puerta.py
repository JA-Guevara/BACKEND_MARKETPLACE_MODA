from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

from scripts import railway_entrypoint as entry
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings

HEAD = "20261110_0032"
PREVIOUS = "20261109_0031"
# UTC ya cambió de día. En La Paz todavía es 05/11.
NOW = datetime(2026, 11, 6, 2, 30, tzinfo=timezone.utc)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is timezone.utc
        return NOW


@pytest.fixture
def gate(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": PREVIOUS})
        connection.execute(text("""
            CREATE TABLE platform_backups (
                verify_status VARCHAR(10), alembic_revision VARCHAR(40), finished_at TIMESTAMP
            )
        """))
        AuditEventModel.__table__.create(connection)

    monkeypatch.setattr(settings, "database_url", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(entry, "create_engine", lambda url: engine)
    dispose = engine.dispose
    monkeypatch.setattr(engine, "dispose", Mock())
    monkeypatch.setattr(entry.ScriptDirectory, "from_config", lambda _: SimpleNamespace(get_current_head=lambda: HEAD))
    monkeypatch.setattr(entry, "_bloquear_migraciones", Mock())
    monkeypatch.setattr(entry, "datetime", FixedDateTime)
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


def _backup(engine, *, age_hours=3, revision=PREVIOUS, status="ok"):
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO platform_backups VALUES (:status, :revision, :finished_at)"),
            {"status": status, "revision": revision, "finished_at": NOW - timedelta(hours=age_hours)},
        )


def test_sin_pendientes_no_migra_ni_requiere_tabla_de_respaldos(gate):
    engine, upgrade = gate
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :revision"), {"revision": HEAD})
        connection.execute(text("DROP TABLE platform_backups"))
    entry.preparar()
    upgrade.assert_not_called()


def test_migra_con_copia_verificada_de_tres_horas_y_no_repite(gate):
    engine, upgrade = gate
    _backup(engine)
    entry.preparar()
    entry.preparar()
    upgrade.assert_called_once()
    assert _revision(engine) == HEAD
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM audit_events")) == 0


@pytest.mark.parametrize(("age_hours", "revision", "status"), [
    (27, PREVIOUS, "ok"),
    (24, PREVIOUS, "ok"),
    (-1, PREVIOUS, "ok"),
    (3, HEAD, "ok"),
    (3, PREVIOUS, "failed"),
])
def test_bloquea_copias_que_no_cumplen_la_puerta(gate, age_hours, revision, status):
    engine, upgrade = gate
    _backup(engine, age_hours=age_hours, revision=revision, status=status)
    with pytest.raises(RuntimeError, match="backup_gate_blocked"):
        entry.preparar()
    upgrade.assert_not_called()
    assert _revision(engine) == PREVIOUS


@pytest.mark.parametrize("fecha", ["2026-11-04", "2026-11-06"])
def test_excepcion_requiere_la_fecha_boliviana(gate, monkeypatch, fecha):
    _, upgrade = gate
    monkeypatch.setenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", fecha)
    with pytest.raises(RuntimeError, match="backup_gate_blocked"):
        entry.preparar()
    upgrade.assert_not_called()


def test_excepcion_hoy_migra_y_audita_incluso_sin_tabla_de_respaldos(gate, monkeypatch, capsys):
    engine, upgrade = gate
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE platform_backups"))
    monkeypatch.setenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", "2026-11-05")
    entry.preparar()
    upgrade.assert_called_once()
    assert _revision(engine) == HEAD
    assert "backup_gate_exception" in capsys.readouterr().out
    with engine.connect() as connection:
        event = connection.execute(AuditEventModel.__table__.select()).mappings().one()
    assert event["tenant_id"] is None
    assert event["actor_user_id"] is None
    assert event["action"] == "platform.migration_without_backup"
    assert event["metadata"] == {
        "revision_previa": PREVIOUS, "revision_nueva": HEAD, "fecha_autorizada": "2026-11-05"
    }


def test_fallo_de_bitacora_revierte_tambien_la_migracion(gate, monkeypatch, capsys):
    engine, upgrade = gate
    monkeypatch.setenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", "2026-11-05")
    monkeypatch.setattr(entry, "_registrar_excepcion", Mock(side_effect=RuntimeError("falló auditoría")))
    with pytest.raises(RuntimeError, match="falló auditoría"):
        entry.preparar()
    upgrade.assert_called_once()
    assert _revision(engine) == PREVIOUS
    assert "backup_gate_exception" not in capsys.readouterr().out


def test_prepare_usa_dueno_sin_cambiar_conexion_de_la_aplicacion(gate, monkeypatch):
    engine, upgrade = gate
    application_url = "postgresql://fashionstore_app@127.0.0.1/qa"
    migration_url = "postgresql://migration_owner@127.0.0.1/qa"
    monkeypatch.setattr(settings, "database_url", application_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_url)
    selected = []
    monkeypatch.setattr(entry, "create_engine", lambda url: selected.append(url) or engine)
    _backup(engine)
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
