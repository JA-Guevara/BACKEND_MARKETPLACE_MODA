"""Evita colisiones reales encontradas al integrar las migraciones de los planes."""
import ast
from pathlib import Path
from uuid import UUID


MIGRATIONS = Path(__file__).resolve().parents[2] / "alembic/versions"


def declared_permissions():
    for path in MIGRATIONS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "NEW_PERMISSIONS" for target in node.targets
            ):
                for row_node in node.value.elts:
                    identifier = row_node.elts[0]
                    if isinstance(identifier, ast.Call):
                        assert isinstance(identifier.func, ast.Name) and identifier.func.id == "UUID"
                        assert len(identifier.args) == 1 and not identifier.keywords
                        identifier = identifier.args[0]
                    # Solo inspección de literales: no importar ni ejecutar migraciones.
                    permission_id = str(UUID(ast.literal_eval(identifier)))
                    yield path.name, permission_id, ast.literal_eval(row_node.elts[1])


def test_las_migraciones_no_reutilizan_uuid_de_otro_permiso():
    """Un UUID puede repetirse solo si es el mismo permiso.

    Las migraciones de reparacion (0031) vuelven a declarar permisos ya
    reservados por 0026/0030 para poder sembrarlos en una base que quedo a
    medio migrar. Eso es seguro mientras el UUID siga apuntando al mismo
    codigo; lo que no puede pasar es que un UUID identifique dos permisos.
    """
    identifiers = {}
    for source, permission_id, code in declared_permissions():
        previous = identifiers.get(permission_id)
        assert previous is None or previous[1] == code, (source, code, previous)
        identifiers[permission_id] = (source, code)


def test_rangos_reservados_por_el_plan_maestro():
    declared = {code: permission_id for _, permission_id, code in declared_permissions()}
    reserved = {
        "exchanges.read": 37, "exchanges.write": 38,
        "ai_reports.use": 39, "ai_reports.history": 40,
        "promotions.read": 43, "promotions.write": 44,
        "devices.read": 45, "devices.write": 46,
        "modules.read": 47, "modules.write": 48,
        "platform_roles.read": 49, "platform_roles.write": 50,
        "tenant_users.write": 51, "sandbox.manage": 52,
        "storefront.write": 53, "payment_methods.write": 54,
        "catalog_templates.write": 55, "upgrade_requests.manage": 56,
        "platform.ops.read": 57, "platform.ops.write": 58, "tenant.data_export": 59,
    }
    for code, suffix in reserved.items():
        assert declared[code] == f"20000000-0000-0000-0000-{suffix:012d}", code
