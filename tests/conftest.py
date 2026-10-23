"""Ajustes comunes a toda la suite.

La cola de correos está encendida por defecto en producción, pero en pruebas
tiene que estar apagada, y no es solo por comodidad:

* Las pruebas comprueban el booleano que devuelve `EnviarCorreo.execute` y el
  evento de bitácora en LA MISMA Session, justo después de llamar. Con el envío
  diferido ninguna de las dos cosas se cumple todavía cuando corre el `assert`.
* Los hilos de la cola abren su propia Session con `SessionLocal`, que apunta a
  `DATABASE_URL`. Las pruebas unitarias trabajan con su propio SQLite en memoria
  y nunca pasan por ahí: si un hilo enviara de verdad, escribiría eventos
  `notificaciones.email_*` en la base REAL, con actores que solo existen en el
  SQLite de la prueba.

Las pruebas que sí ejercitan la cola la encienden ellas mismas dentro del test,
con su propia instancia de `ColaDeCorreos` y su propia fábrica de Session.
"""
import pytest
import os

# Las pruebas nunca deben usar servicios configurados en el .env del equipo.
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:1/fashionstore_test"
os.environ["EMAIL_BACKGROUND"] = "false"
os.environ["SMTP_HOST"] = ""
os.environ["AI_API_KEY"] = ""
os.environ["STRIPE_SECRET_KEY"] = ""

from src.infrastructure.config.settings import settings

settings.email_background = False

# Compatibilidad de los mundos del primer parcial: cada SQLite independiente
# representa la empresa inicial. No hay defaults multiempresa en producción.
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel, PlanFeatureModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.domain.estados import FUNCIONES

DEFAULT_TENANT_ID = UUID("30000000-0000-0000-0000-000000000001")


@event.listens_for(Session, "before_flush")
def legacy_tenant_fixture(db, flush_context, instances):
    if db.get_bind().dialect.name != "sqlite":
        return
    affected = [obj for obj in db.new if hasattr(obj, "tenant_id") and obj.__tablename__ in
                {"users", "branches", "cash_points", "products", "reservations"}]
    if not affected:
        return
    connection = db.connection()
    if not connection.scalar(select(TenantModel.id).where(TenantModel.id == DEFAULT_TENANT_ID)):
        now = datetime.now(timezone.utc)
        connection.execute(TenantModel.__table__.insert().values(id=DEFAULT_TENANT_ID, legal_name="FashionStore", trade_name="FashionStore", tax_id="0000000001", slug="fashionstore", contact_email="contacto@fashionstore.test", status="ACTIVA", created_at=now, updated_at=now))
        plan_id = uuid4()
        connection.execute(PlanModel.__table__.insert().values(id=plan_id, code="LEGACY_TEST", name="Pruebas", reference_price=0, duration_days=365, is_active=True, created_at=now, updated_at=now))
        connection.execute(PlanFeatureModel.__table__.insert(), [dict(id=uuid4(), plan_id=plan_id, feature_code=code, enabled=True, limit_value=1000 if code == "max_active_branches" else None) for code in (*FUNCIONES, "max_active_branches")])
        connection.execute(SubscriptionModel.__table__.insert().values(id=uuid4(), tenant_id=DEFAULT_TENANT_ID, plan_id=plan_id, start_date=date.today(), end_date=date.today()+timedelta(days=365), status="ACTIVA", created_at=now, updated_at=now))
    for obj in affected:
        if obj.tenant_id is None and not (obj.__tablename__ == "users" and any(role.code == "platform_admin" for role in obj.roles)):
            obj.tenant_id = DEFAULT_TENANT_ID


@pytest.fixture(autouse=True)
def correo_en_linea():
    """Cada prueba arranca con el envío en línea, pase lo que pase en la anterior."""
    anterior = settings.email_background
    settings.email_background = False
    yield
    settings.email_background = anterior
