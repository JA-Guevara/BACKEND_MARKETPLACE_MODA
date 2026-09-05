from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
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


config = context.config
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


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
