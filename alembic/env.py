from logging.config import fileConfig
from src.plataforma_saas.infrastructure.models import tenant, plan, subscription, support_session  # noqa: F401

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.infrastructure.config.settings import settings
from src.infrastructure.database.safety import require_environment_match, require_local_database
from src.infrastructure.database.base import Base
from src.ventas_pagos.infrastructure.models import StockModel, CartItemModel, OrderModel, WebhookEventModel
from src.ventas_pagos.infrastructure.engagement_models import FavoriteModel, PromotionModel, PromotionUseModel
from src.auth.infrastructure.persistence.models.email_verification_token import EmailVerificationTokenModel
from src.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.usuarios.infrastructure.persistence.models.usuario import AddressModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel, CityModel, SupplierModel
from src.usuarios_catalogo.infrastructure.models.catalog import ARAssetModel, CategoryModel, CollectionModel, ColorModel, ProductImageModel, ProductModel, ProductSupplierModel, ProductVariantModel, SeasonModel, SizeModel
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
# Registro explícito de todos los modelos para que autogenerate/alembic check
# comparen el esquema completo, incluso módulos sin rutas importadas aquí.
from src.analitica_ml.infrastructure import models as ml_models  # noqa: F401
from src.dispositivos.infrastructure import models as device_models  # noqa: F401
from src.operacion_offline.infrastructure.models import sync as sync_models  # noqa: F401
from src.plataforma_saas.infrastructure.models import module, ops, storefront  # noqa: F401
from src.probador_virtual.infrastructure.persistence.models import recurso_tryon  # noqa: F401
from src.reportes_ia.infrastructure import models as report_models  # noqa: F401
from src.tryon_ai_jobs.infrastructure.persistence.models import tryon_job  # noqa: F401


config = context.config
require_local_database(settings.database_url)
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Permite que un script externo abra la transaccion y pase la conexion
    # (necesario para corregir el sello de produccion y migrar de forma atomica).
    external_connection = config.attributes.get("connection")
    if external_connection is not None:
        require_environment_match(settings.app_env, external_connection.engine.url, settings.production_db_host)
        require_local_database(external_connection.engine.url)
        _run_migrations(external_connection)
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
