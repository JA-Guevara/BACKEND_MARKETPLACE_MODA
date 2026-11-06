"""La cadena real debe migrar, coincidir con ORM y ser reversible desde 0031."""
from tests.integration.database.test_metadata_alembic import local_database  # noqa: F401


def test_upgrade_vacio_hasta_head(local_database):
    _, migrate = local_database
    migrate("upgrade", "head")


def test_alembic_check_tras_upgrade(local_database):
    _, migrate = local_database
    migrate("upgrade", "head")
    migrate("check")


def test_ciclo_0031_head_con_check_final(local_database):
    _, migrate = local_database
    migrate("upgrade", "head")
    migrate("downgrade", "20261109_0031")
    migrate("upgrade", "head")
    migrate("check")
