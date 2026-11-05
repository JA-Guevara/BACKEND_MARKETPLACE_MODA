from datetime import datetime, timedelta, timezone

from src.plataforma_saas.domain.modulos import (
    Lifecycle,
    ModuloEfectivo,
    Override,
    OverrideMode,
    modulos_efectivos,
    permisos_bloqueados,
    puede_pasar_a,
)


def _catalogo_completo():
    return {
        "products": {"kind": "BASE", "lifecycle": "GA"},
        "inventory": {"kind": "ADDON", "lifecycle": "GA"},
        "sales": {"kind": "ADDON", "lifecycle": "GA"},
        "reservations": {"kind": "ADDON", "lifecycle": "GA"},
        "offline": {"kind": "ADDON", "lifecycle": "GA"},
        "conventional_reports": {"kind": "ADDON", "lifecycle": "GA"},
        "ai_reports": {"kind": "ADDON", "lifecycle": "GA"},
        "ml_analytics": {"kind": "ADDON", "lifecycle": "GA"},
        "promotions": {"kind": "ADDON", "lifecycle": "GA"},
        "virtual_tryon": {"kind": "ADDON", "lifecycle": "GA"},
        "exchanges": {"kind": "ADDON", "lifecycle": "BETA"},
        "devices_audit": {"kind": "ADDON", "lifecycle": "BETA"},
        "legacy_module": {"kind": "ADDON", "lifecycle": "RETIRADO"},
    }


def test_plan_mas_extra_mas_trial_vigente():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    catalogo = _catalogo_completo()
    plan = {"sales"}
    overrides = [
        Override(
            module_code="virtual_tryon",
            mode=OverrideMode.EXTRA,
            starts_at=now - timedelta(days=5),
        ),
        Override(
            module_code="ai_reports",
            mode=OverrideMode.TRIAL,
            starts_at=now - timedelta(days=2),
            expires_at=now + timedelta(days=5),
        ),
    ]

    efectivos = modulos_efectivos(catalogo, plan, overrides, sandbox=False, now=now)

    assert set(efectivos.keys()) == {"products", "sales", "virtual_tryon", "ai_reports"}
    assert efectivos["products"].origen == "BASE"
    assert efectivos["sales"].origen == "PLAN"
    assert efectivos["virtual_tryon"].origen == "EXTRA"
    assert efectivos["ai_reports"].origen == "TRIAL"


def test_trial_vencido_ayer_no_aparece():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    catalogo = _catalogo_completo()
    plan = {"sales"}
    overrides = [
        Override(
            module_code="ai_reports",
            mode=OverrideMode.TRIAL,
            starts_at=now - timedelta(days=8),
            expires_at=now - timedelta(days=1),
        ),
    ]

    efectivos = modulos_efectivos(catalogo, plan, overrides, sandbox=False, now=now)

    assert "ai_reports" not in efectivos
    assert "sales" in efectivos
    assert "products" in efectivos


def test_bloqueado_quita_modulo_salvo_base():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    catalogo = _catalogo_completo()
    plan = {"promotions"}
    overrides = [
        Override(
            module_code="promotions",
            mode=OverrideMode.BLOQUEADO,
            starts_at=now - timedelta(days=1),
        ),
        Override(
            module_code="products",
            mode=OverrideMode.BLOQUEADO,
            starts_at=now - timedelta(days=1),
        ),
    ]

    efectivos = modulos_efectivos(catalogo, plan, overrides, sandbox=False, now=now)

    assert "promotions" not in efectivos
    assert "products" in efectivos
    assert efectivos["products"].origen == "BASE"


def test_sandbox_activa_todos_menos_retirado():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    catalogo = _catalogo_completo()
    plan = set()
    overrides = []

    efectivos = modulos_efectivos(catalogo, plan, overrides, sandbox=True, now=now)

    assert "legacy_module" not in efectivos
    assert "products" in efectivos
    assert efectivos["products"].origen == "BASE"
    assert efectivos["virtual_tryon"].origen == "SANDBOX"
    assert efectivos["exchanges"].origen == "SANDBOX"
    assert efectivos["ai_reports"].origen == "SANDBOX"
    assert len(efectivos) == 12


def test_beta_en_plan_no_aparece_pero_como_trial_si():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    catalogo = _catalogo_completo()
    plan = {"exchanges"}  # exchanges is BETA
    overrides = []

    # En plan pero BETA -> no entra
    efectivos1 = modulos_efectivos(catalogo, plan, overrides, sandbox=False, now=now)
    assert "exchanges" not in efectivos1

    # BETA como TRIAL activo -> sí entra
    overrides_trial = [
        Override(
            module_code="exchanges",
            mode=OverrideMode.TRIAL,
            starts_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=7),
        )
    ]
    efectivos2 = modulos_efectivos(catalogo, plan, overrides_trial, sandbox=False, now=now)
    assert "exchanges" in efectivos2
    assert efectivos2["exchanges"].origen == "TRIAL"


def test_permisos_bloqueados():
    permisos_rol = {"commerce.write", "users.read"}
    modulo_de = {"commerce.write": "sales"}
    efectivos = set()

    bloqueados = permisos_bloqueados(permisos_rol, modulo_de, efectivos)
    assert bloqueados == {"commerce.write"}

    # Si sales está activo, no está bloqueado
    bloqueados_activo = permisos_bloqueados(permisos_rol, modulo_de, {"sales"})
    assert bloqueados_activo == set()


def test_puede_pasar_a():
    assert puede_pasar_a(Lifecycle.BETA, Lifecycle.GA, revisado=False) == "module_not_reviewed"
    assert puede_pasar_a(Lifecycle.BETA, Lifecycle.GA, revisado=True) is None
    assert puede_pasar_a(Lifecycle.RETIRADO, Lifecycle.GA, revisado=True) == "module_retired"
    assert puede_pasar_a(Lifecycle.BORRADOR, Lifecycle.BETA, revisado=False) is None


def test_asignacion_futura_no_habilita_ni_bloquea_antes_de_su_inicio():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    overrides = [
        Override("ai_reports", OverrideMode.EXTRA, starts_at=now + timedelta(hours=1)),
        Override("sales", OverrideMode.BLOQUEADO, starts_at=now + timedelta(hours=1)),
    ]
    result = modulos_efectivos(_catalogo_completo(), {"sales"}, overrides, False, now)
    assert "ai_reports" not in result
    assert result["sales"].origen == "PLAN"


def test_revocada_o_expirada_no_habilita_y_retirado_nunca_se_reactiva():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    overrides = [
        Override("ai_reports", "EXTRA", starts_at=now, revoked_at=now),
        Override("virtual_tryon", "EXTRA", starts_at=now, expires_at=now),
        Override("legacy_module", "TRIAL", starts_at=now, expires_at=now + timedelta(days=1)),
    ]
    assert set(modulos_efectivos(_catalogo_completo(), set(), overrides, False, now)) == {"products"}
