from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.plataforma_saas.infrastructure.models.module import PlatformModuleModel, TenantLimitModel, TenantModuleModel
from src.plataforma_saas.infrastructure.models.plan import PlanFeatureModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel


def _seed_platform_modules(world):
    db = world.db
    if not db.scalars(select(PlatformModuleModel)).all():
        modules = [
            PlatformModuleModel(code="products", name="Catálogo y prendas", kind="BASE", lifecycle="GA", sort_order=1),
            PlatformModuleModel(code="inventory", name="Inventario", kind="ADDON", lifecycle="GA", sort_order=2),
            PlatformModuleModel(code="sales", name="Ventas y caja", kind="ADDON", lifecycle="GA", sort_order=3),
            PlatformModuleModel(code="reservations", name="Reservas", kind="ADDON", lifecycle="GA", sort_order=4),
            PlatformModuleModel(code="offline", name="Operación sin conexión", kind="ADDON", lifecycle="GA", sort_order=5),
            PlatformModuleModel(code="conventional_reports", name="Reportes convencionales", kind="ADDON", lifecycle="GA", sort_order=6),
            PlatformModuleModel(code="ai_reports", name="Reportes con IA", kind="ADDON", lifecycle="GA", sort_order=7),
            PlatformModuleModel(code="ml_analytics", name="Analítica predictiva (ML)", kind="ADDON", lifecycle="GA", sort_order=8),
            PlatformModuleModel(code="promotions", name="Ofertas y promociones", kind="ADDON", lifecycle="GA", sort_order=9),
            PlatformModuleModel(code="virtual_tryon", name="Probador virtual (RA)", kind="ADDON", lifecycle="GA", sort_order=10),
            PlatformModuleModel(code="exchanges", name="Cambios de prendas", kind="ADDON", lifecycle="BETA", sort_order=11),
            PlatformModuleModel(code="devices_audit", name="Dispositivos y auditoría", kind="ADDON", lifecycle="BETA", sort_order=12),
        ]
        db.add_all(modules)
        db.flush()

    new_perms = [
        ("modules.read", "platform"),
        ("modules.write", "platform"),
        ("platform_roles.read", "platform"),
        ("platform_roles.write", "platform"),
        ("tenant_users.write", "platform"),
        ("sandbox.manage", "platform"),
    ]
    for pcode, pscope in new_perms:
        existing = db.scalars(select(PermissionModel).where(PermissionModel.code == pcode)).first()
        if not existing:
            p = PermissionModel(code=pcode, name=pcode, module="platform", scope=pscope)
            db.add(p)
            db.flush()
            plat_role = db.scalars(select(RoleModel).where(RoleModel.code == "platform_admin")).first()
            if plat_role and p not in plat_role.permissions:
                plat_role.permissions.append(p)
    from src.plataforma_saas.application.entitlement_service import DEFAULT_MODULE_PERMISSION_MAPPING
    for permission in db.scalars(select(PermissionModel)):
        code = DEFAULT_MODULE_PERMISSION_MAPPING.get(permission.code)
        module = db.get(PlatformModuleModel, code) if code else None
        if module is not None and permission not in module.permissions:
            module.permissions.append(permission)
    db.commit()


def test_administrador_empresa_no_puede_llamar_platform_modules(world):
    _seed_platform_modules(world)
    resp = world.client.get("/api/v1/platform/modules", headers=world.headers(world.admins[0]))
    assert resp.status_code == 403


def test_platform_admin_puede_listar_modules(world):
    _seed_platform_modules(world)
    resp = world.client.get("/api/v1/platform/modules", headers=world.headers(world.platform))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(m["code"] == "products" for m in data)


def test_agregar_exchanges_beta_a_plan_retorna_409_module_in_beta(world):
    _seed_platform_modules(world)
    plan = world.plans[0]
    payload = {
        "features": [
            {"feature_code": "exchanges", "enabled": True},
            {"feature_code": "max_active_branches", "enabled": True, "limit_value": 2},
        ]
    }
    resp = world.client.put(f"/api/v1/platform/plans/{plan.id}", json=payload, headers=world.headers(world.platform))
    assert resp.status_code == 409
    assert resp.json().get("code") == "module_in_beta" or resp.json().get("error", {}).get("code") == "module_in_beta"


def test_dar_trial_ai_reports_a_empresa_a_y_aislamiento_con_b(world):
    _seed_platform_modules(world)
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    # Empresa A (Básico) inicialmente no tiene ai_reports
    resp_me_a = world.client.get("/api/v1/auth/me", headers=world.headers(world.admins[0]))
    assert resp_me_a.status_code == 200
    assert resp_me_a.json()["data"]["subscription"]["features"].get("ai_reports") is False

    # Dar TRIAL de 7 días de ai_reports a Empresa A
    grant_payload = {
        "module_code": "ai_reports",
        "mode": "TRIAL",
        "days": 7,
        "reason": "Prueba de módulo IA para cliente A",
    }
    resp_grant = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/modules",
        json=grant_payload,
        headers=world.headers(world.platform),
    )
    assert resp_grant.status_code == 201

    # Verificar que Empresa A ahora tiene ai_reports como TRIAL
    resp_me_a2 = world.client.get("/api/v1/auth/me", headers=world.headers(world.admins[0]))
    assert resp_me_a2.status_code == 200
    sub_data = resp_me_a2.json()["data"]["subscription"]
    assert sub_data["features"]["ai_reports"] is True
    assert any(m["code"] == "ai_reports" and m["origin"] == "TRIAL" for m in sub_data["modules"])

    # Aislamiento: Empresa B sigue con su plan y no recibe el TRIAL de A
    resp_me_b = world.client.get("/api/v1/auth/me", headers=world.headers(world.admins[1]))
    assert resp_me_b.status_code == 200
    sub_data_b = resp_me_b.json()["data"]["subscription"]
    assert not any(m["code"] == "ai_reports" and m["origin"] == "TRIAL" for m in sub_data_b["modules"])


def test_quitar_modulo_con_empresas_sin_confirm_retorna_409(world):
    _seed_platform_modules(world)
    plan_pro = world.plans[1]

    features_sin_tryon = [
        {
            "feature_code": f.feature_code,
            "enabled": False if f.feature_code in ("virtual_tryon", "exchanges", "devices_audit") else f.enabled,
            "limit_value": f.limit_value,
        }
        for f in plan_pro.features
    ]
    resp = world.client.put(
        f"/api/v1/platform/plans/{plan_pro.id}",
        json={"features": features_sin_tryon, "confirm": False},
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 409
    err_code = resp.json().get("code") or resp.json().get("error", {}).get("code")
    assert err_code == "impact_confirmation_required"


def test_cajero_con_commerce_write_sin_sales_retorna_403(world):
    _seed_platform_modules(world)
    tenant_a = world.tenants[0]

    comm_perm = world.db.scalars(select(PermissionModel).where(PermissionModel.code == "commerce.write")).first()
    if not comm_perm:
        comm_perm = PermissionModel(code="commerce.write", name="Ventas", module="commerce", scope="tenant")
        world.db.add(comm_perm)
        world.db.flush()

    role_cajero = RoleModel(tenant_id=tenant_a.id, code="cajero_test", name="Cajero Test", permissions=[comm_perm])
    cajero = UserModel(
        tenant_id=tenant_a.id,
        email="cajero_bloqueado@example.com",
        first_name="Cajero",
        last_name="Test",
        password_hash=PasswordHasher().hash("Pass!2026Strong"),
        is_verified=True,
        roles=[role_cajero],
    )
    world.db.add_all([role_cajero, cajero])
    world.db.commit()

    # Bloquear módulo sales para Empresa A
    world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/modules",
        json={"module_code": "sales", "mode": "BLOQUEADO", "reason": "Bloqueo comercial"},
        headers=world.headers(world.platform),
    )

    # Intento de venta presencial por el cajero
    resp_venta = world.client.post(
        "/api/v1/commerce/admin/pos/sales",
        json={"items": [], "payment_method": "CASH"},
        headers=world.headers(cajero),
    )
    assert resp_venta.status_code == 403
    assert resp_venta.json()["error"]["code"] == "feature_not_in_plan"


def test_limite_por_empresa_se_refleja_en_resumen_y_no_afecta_otra(world):
    from src.plataforma_saas.application.plan_guard import PlanGuard
    _seed_platform_modules(world)
    world.db.add(TenantLimitModel(tenant_id=world.tenants[0].id, limit_code="max_active_branches",
        value=5, expires_at=datetime.now(timezone.utc)+timedelta(days=2), reason="Ampliación temporal"))
    world.db.commit()
    assert PlanGuard(world.db).resumen(world.tenants[0].id).limits["max_active_branches"] == 5
    PlanGuard(world.db).exigir_limite(world.tenants[0].id, "max_active_branches", 4)
    assert PlanGuard(world.db).resumen(world.tenants[1].id).limits["max_active_branches"] == 10
    override = world.db.scalar(select(TenantLimitModel).where(TenantLimitModel.tenant_id == world.tenants[0].id))
    override.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    world.db.commit()
    assert PlanGuard(world.db).resumen(world.tenants[0].id).limits["max_active_branches"] == 2


def test_impacto_conserva_prueba_y_extra_e_ignora_bloqueo_ya_activo(world):
    from src.plataforma_saas.application.entitlement_service import EntitlementService
    _seed_platform_modules(world)
    world.db.add(TenantModuleModel(tenant_id=world.tenants[1].id, module_code="ai_reports", mode="TRIAL",
        starts_at=datetime.now(timezone.utc)-timedelta(days=1), expires_at=datetime.now(timezone.utc)+timedelta(days=2),
        reason="Prueba autorizada"))
    world.db.add(TenantModuleModel(tenant_id=world.tenants[1].id, module_code="sales", mode="BLOQUEADO",
        starts_at=datetime.now(timezone.utc)-timedelta(days=1), reason="Bloqueo vigente"))
    world.db.commit()
    features = {feature.feature_code: feature.enabled for feature in world.plans[1].features if feature.feature_code != "max_active_branches"}
    features.update(ai_reports=False, sales=False)
    impact = EntitlementService(world.db).impacto_plan(world.plans[1].id, features)
    assert impact.affected_tenants == 0
    assert impact.affected_users == 0
    assert impact.permissions_lost == []
    override = world.db.scalar(select(TenantModuleModel).where(TenantModuleModel.module_code == "ai_reports"))
    override.mode = "EXTRA"
    override.expires_at = None
    world.db.commit()
    assert EntitlementService(world.db).impacto_plan(world.plans[1].id, features).affected_tenants == 0


def test_catalogo_vivo_acepta_modulo_registrado_y_rechaza_codigo_inventado(world):
    _seed_platform_modules(world)
    world.db.add(PlatformModuleModel(code="nuevo_modulo", name="Nuevo módulo", kind="ADDON", lifecycle="GA"))
    world.db.commit()
    headers = world.headers(world.platform)
    payload = {"code": "PLAN_NUEVO", "name": "Nuevo", "reference_price": 10, "duration_days": 30,
        "features": [{"feature_code": "nuevo_modulo", "enabled": True},
                     {"feature_code": "max_active_branches", "enabled": True, "limit_value": 2}]}
    result = world.client.post("/api/v1/platform/plans", headers=headers, json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["data"]["plan"]["features"]["nuevo_modulo"] is True
    payload["code"] = "PLAN_INVALIDO"
    payload["features"][0]["feature_code"] = "inventado"
    assert world.client.post("/api/v1/platform/plans", headers=headers, json=payload).status_code == 422


def test_modulo_revisado_puede_pasar_a_ga_y_plan_con_motivo(world):
    from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
    _seed_platform_modules(world)
    module = world.db.get(PlatformModuleModel, "exchanges")
    module.last_preview_at = datetime.now(timezone.utc)
    world.db.commit()
    headers = world.headers(world.platform)
    assert world.client.patch("/api/v1/platform/modules/exchanges", headers=headers, json={"lifecycle": "GA"}).status_code == 200
    features = [{"feature_code": f.feature_code, "enabled": f.enabled, "limit_value": f.limit_value}
                for f in world.plans[0].features if f.feature_code not in {"exchanges", "devices_audit"}]
    features.append({"feature_code": "exchanges", "enabled": True})
    result = world.client.patch(f"/api/v1/platform/plans/{world.plans[0].id}", headers=headers,
        json={"features": features, "confirm": True, "reason": "Módulo revisado en la demo"})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["plan"]["features"]["exchanges"] is True
    event = world.db.scalar(select(AuditEventModel).where(
        AuditEventModel.action == "plans.updated", AuditEventModel.entity_id == str(world.plans[0].id)))
    assert event.metadata_["reason"] == "Módulo revisado en la demo"


def test_retirado_no_se_reactiva_y_dependencias_no_pueden_formar_ciclos(world):
    _seed_platform_modules(world)
    module = world.db.get(PlatformModuleModel, "exchanges")
    module.lifecycle = "RETIRADO"
    module.last_preview_at = datetime.now(timezone.utc)
    world.db.commit()
    headers = world.headers(world.platform)
    response = world.client.patch("/api/v1/platform/modules/exchanges", headers=headers, json={"lifecycle": "GA"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "module_retired"
    response = world.client.patch("/api/v1/platform/modules/products", headers=headers, json={"depends_on": ["products"]})
    assert response.status_code == 422
    response = world.client.patch("/api/v1/platform/modules/products", headers=headers, json={"lifecycle": "INVENTADO"})
    assert response.status_code == 422


def test_error_sql_no_se_oculta_como_catalogo_predeterminado(world, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from src.plataforma_saas.application.entitlement_service import EntitlementService
    world.db.info.clear()
    def fail(*args, **kwargs):
        raise SQLAlchemyError("Fallo sintético")
    monkeypatch.setattr(world.db, "scalars", fail)
    with pytest.raises(SQLAlchemyError):
        EntitlementService(world.db)._get_catalog()


def test_equipo_platform_respeta_permisos_sin_exigir_rol_superadmin(world):
    _seed_platform_modules(world)
    read_plans = world.db.scalar(select(PermissionModel).where(PermissionModel.code == "plans.read"))
    role = RoleModel(code="platform_billing_qa", name="Comercial QA", audience="PLATFORM", permissions=[read_plans])
    user = UserModel(email="comercial-platform@example.com", first_name="QA", last_name="Comercial",
        password_hash=world.platform.password_hash, is_verified=True, roles=[role])
    world.db.add(user)
    world.db.commit()
    # El fixture histórico asigna empresa a toda cuenta nueva salvo
    # platform_admin; este caso representa un miembro del equipo PLATFORM.
    user.tenant_id = None
    world.db.commit()
    assert world.client.get("/api/v1/platform/plans", headers=world.headers(user)).status_code == 200
    assert world.client.get("/api/v1/platform/modules", headers=world.headers(user)).status_code == 403
