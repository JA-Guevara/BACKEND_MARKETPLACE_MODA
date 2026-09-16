"""Contrato de las herramientas tipadas del asistente: allowlist estricta,
parametros validados, bitacora con correo del actor e idempotencia por
request_id (una sola auditoria por operacion)."""
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.database.base import Base
from src.ventas_pagos.application.assistant_tools import AssistantTools, UnknownToolError
from src.ventas_pagos.web.schemas import ExportReportToolParams

WORLD = None


def make_world() -> tuple[Session, UserModel]:
    global WORLD
    if WORLD:
        return WORLD
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    actor = UserModel(email="analista@fashionstore.test", password_hash="x", first_name="Ana", last_name="Reportes",
                      is_active=True, is_verified=True)
    db.add(actor)
    db.commit()
    WORLD = (db, actor)
    return WORLD


def events(db, action: str) -> list[AuditEventModel]:
    return list(db.scalars(select(AuditEventModel).where(AuditEventModel.action == action)))


def test_herramienta_no_autorizada_es_rechazada():
    db, actor = make_world()
    tools = AssistantTools(db)
    try:
        tools.execute("sql_query", None, actor, None)  # type: ignore[arg-type]
        assert False, "debio rechazarse la herramienta inventada"
    except UnknownToolError:
        pass


def test_export_report_ejecuta_y_audita_con_correo():
    db, actor = make_world()
    params = ExportReportToolParams(reports=["ventas"], format="xlsx")
    result = AssistantTools(db).execute("export_report", params, actor, "req-001")
    assert result.reports == ["Ventas diarias (ingresos cobrados)"]
    assert result.filename.endswith(".xlsx")
    assert result.audited is True and result.replay is False
    row = events(db, "analytics.tool_export_report")[-1]
    assert row.actor_user_id == actor.id
    assert row.metadata_["actor_email"] == "analista@fashionstore.test"
    assert row.metadata_["request_id"] == "req-001"
    assert row.metadata_["tool"] == "export_report"


def test_request_id_repetida_no_vuelve_a_auditar():
    db, actor = make_world()
    before = len(events(db, "analytics.tool_export_report"))
    params = ExportReportToolParams(reports=["pedidos"], format="csv")
    tools = AssistantTools(db)
    first = tools.execute("export_report", params, actor, "req-replay")
    second = tools.execute("export_report", params, actor, "req-replay")
    assert first.replay is False and first.audited is True
    assert second.replay is True and second.audited is False
    assert len(events(db, "analytics.tool_export_report")) == before + 1


def test_mismo_usuario_puede_repetir_con_otra_request_id():
    db, actor = make_world()
    params = ExportReportToolParams(reports=["pagos"], format="pdf")
    tools = AssistantTools(db)
    other = uuid.uuid4().hex[:12]
    first = tools.execute("export_report", params, actor, other)
    second = tools.execute("export_report", params, actor, uuid.uuid4().hex[:12])
    assert first.replay is False
    assert second.replay is False