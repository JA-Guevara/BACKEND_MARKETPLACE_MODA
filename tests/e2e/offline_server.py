"""API sintética exclusiva para el ensayo PWA. Nunca carga una base remota."""
import os
from pathlib import Path
import sys
from tempfile import mkstemp

backend = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend))
os.chdir(backend)
os.environ.update(APP_ENV="test", DATABASE_URL="sqlite+pysqlite:///:memory:",
                  RATE_LIMIT_ENABLED="false", SMTP_HOST="", EMAIL_BACKGROUND="false",
                  AI_API_KEY="", STRIPE_SECRET_KEY="", DEBUG="false")

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session
import uvicorn
from src.infrastructure.database.session import get_db
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from tests.unit.plataforma_saas.conftest import create_world

descriptor, filename = mkstemp(prefix="fashionstore-offline-ui-", suffix=".db")
os.close(descriptor)
database_file = Path(filename)
engine = create_engine("sqlite+pysqlite:///" + database_file.as_posix(), connect_args={"check_same_thread": False})
world = create_world(engine)


def session_qa():
    with Session(engine, expire_on_commit=False) as db:
        yield db


world.app.dependency_overrides[get_db] = session_qa


@world.app.get("/qa/estado")
def estado_qa():
    with Session(engine) as db:
        return {
            "ventas": db.scalar(select(func.count()).select_from(OrderModel)),
            "stock": db.scalar(select(StockModel.quantity).where(
                StockModel.variant_id == world.variant_a.id, StockModel.branch_id == world.branch_a.id)),
        }


@world.app.post("/qa/stock/{quantity}")
def stock_qa(quantity: int):
    with Session(engine) as db:
        db.execute(update(StockModel).where(StockModel.variant_id == world.variant_a.id,
                                           StockModel.branch_id == world.branch_a.id).values(quantity=quantity))
        db.commit()
    return {"ok": True}


if __name__ == "__main__":
    try:
        uvicorn.run(world.app, host="127.0.0.1", port=57519, log_level="warning")
    finally:
        world.client.close()
        world.db.close()
        engine.dispose()
        database_file.unlink(missing_ok=True)
