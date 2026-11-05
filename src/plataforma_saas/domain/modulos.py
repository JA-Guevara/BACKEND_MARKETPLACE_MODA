from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal


class Lifecycle(StrEnum):
    BORRADOR = "BORRADOR"
    BETA = "BETA"
    GA = "GA"
    RETIRADO = "RETIRADO"


class OverrideMode(StrEnum):
    EXTRA = "EXTRA"
    TRIAL = "TRIAL"
    BLOQUEADO = "BLOQUEADO"


@dataclass(frozen=True)
class Override:
    module_code: str
    mode: OverrideMode | str
    starts_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    reason: str = ""
    granted_by: Any = None


@dataclass(frozen=True)
class ModuloEfectivo:
    code: str
    origen: Literal["BASE", "PLAN", "EXTRA", "TRIAL", "SANDBOX"]
    expira: datetime | None = None


def _normalize_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _get_kind_and_lifecycle(val: Any) -> tuple[str, Lifecycle]:
    if hasattr(val, "kind") and hasattr(val, "lifecycle"):
        kind = str(val.kind).upper()
        lifecycle = Lifecycle(val.lifecycle) if isinstance(val.lifecycle, Lifecycle) else Lifecycle(str(val.lifecycle).upper())
        return kind, lifecycle
    if isinstance(val, dict):
        kind = str(val.get("kind", "ADDON")).upper()
        raw_lc = str(val.get("lifecycle", "GA")).upper()
        return kind, Lifecycle(raw_lc)
    if isinstance(val, (tuple, list)) and len(val) >= 2:
        kind = str(val[0]).upper()
        return kind, Lifecycle(str(val[1]).upper())
    if isinstance(val, Lifecycle):
        return ("BASE" if str(val) == "products" else "ADDON"), val
    raw = str(val).upper()
    if raw in Lifecycle.__members__:
        return "ADDON", Lifecycle(raw)
    return "ADDON", Lifecycle.GA


def modulos_efectivos(
    catalogo: dict[str, Any],
    plan: set[str],
    overrides: list[Override],
    sandbox: bool,
    now: datetime,
) -> dict[str, ModuloEfectivo]:
    now_norm = _normalize_dt(now) or datetime.now(timezone.utc)
    res: dict[str, ModuloEfectivo] = {}

    # Reglas en orden:
    # 1. RETIRADO nunca está activo.
    # 2. BASE siempre está activo.
    # 3. Empresa demo (is_sandbox): todos los demás módulos activos (origen SANDBOX).
    if sandbox:
        for code, info in catalogo.items():
            kind, lifecycle = _get_kind_and_lifecycle(info)
            if lifecycle == Lifecycle.RETIRADO:
                continue
            if kind == "BASE":
                res[code] = ModuloEfectivo(code=code, origen="BASE", expira=None)
            else:
                res[code] = ModuloEfectivo(code=code, origen="SANDBOX", expira=None)
        return res

    # 2. BASE siempre está activo (origen BASE).
    for code, info in catalogo.items():
        kind, lifecycle = _get_kind_and_lifecycle(info)
        if lifecycle == Lifecycle.RETIRADO:
            continue
        if kind == "BASE":
            res[code] = ModuloEfectivo(code=code, origen="BASE", expira=None)

    # 4. Plan vigente: plan_features.enabled y módulo GA (origen PLAN).
    for code in plan:
        if code in catalogo:
            kind, lifecycle = _get_kind_and_lifecycle(catalogo[code])
            if lifecycle == Lifecycle.RETIRADO:
                continue
            if kind == "BASE":
                continue
            if lifecycle == Lifecycle.GA:
                res[code] = ModuloEfectivo(code=code, origen="PLAN", expira=None)

    # 5. EXTRA activo (origen EXTRA).
    # 6. TRIAL con expires_at > ahora (origen TRIAL); BETA solo entra por 5 o 6.
    # 7. BLOQUEADO activo quita el módulo aunque venga del plan, extra o prueba (salvo BASE).
    # Separamos en dos pasadas de overrides: primero activaciones (EXTRA/TRIAL), luego bloqueos
    activations: list[Override] = []
    blocks: list[Override] = []

    for ov in overrides:
        if ov.revoked_at is not None:
            continue
        starts = _normalize_dt(ov.starts_at)
        if starts is not None and starts > now_norm:
            continue
        exp = _normalize_dt(ov.expires_at)
        mode_str = str(ov.mode).upper()
        if mode_str == OverrideMode.TRIAL or mode_str == "TRIAL":
            if exp is None or exp <= now_norm:
                continue
            activations.append(ov)
        elif mode_str == OverrideMode.EXTRA or mode_str == "EXTRA":
            if exp is not None and exp <= now_norm:
                continue
            activations.append(ov)
        elif mode_str == OverrideMode.BLOQUEADO or mode_str == "BLOQUEADO":
            if exp is not None and exp <= now_norm:
                continue
            blocks.append(ov)

    for ov in activations:
        code = ov.module_code
        if code not in catalogo:
            continue
        kind, lifecycle = _get_kind_and_lifecycle(catalogo[code])
        if lifecycle == Lifecycle.RETIRADO:
            continue
        if kind == "BASE":
            continue
        mode_str = str(ov.mode).upper()
        if mode_str == OverrideMode.EXTRA or mode_str == "EXTRA":
            res[code] = ModuloEfectivo(code=code, origen="EXTRA", expira=ov.expires_at)
        elif mode_str == OverrideMode.TRIAL or mode_str == "TRIAL":
            # Si ya está como EXTRA, EXTRA prevalece
            if code not in res or res[code].origen != "EXTRA":
                res[code] = ModuloEfectivo(code=code, origen="TRIAL", expira=ov.expires_at)

    for ov in blocks:
        code = ov.module_code
        if code not in catalogo:
            continue
        kind, _ = _get_kind_and_lifecycle(catalogo[code])
        if kind == "BASE":
            # BASE no se puede bloquear
            continue
        if code in res:
            del res[code]

    return res


def permisos_bloqueados(
    permisos_rol: set[str],
    modulo_de: dict[str, str],
    efectivos: set[str],
) -> set[str]:
    """Permisos cuyo módulo no está activo. Los permisos sin módulo siempre pasan."""
    bloqueados: set[str] = set()
    for perm in permisos_rol:
        if perm in modulo_de:
            mod = modulo_de[perm]
            if mod not in efectivos:
                bloqueados.add(perm)
    return bloqueados


def puede_pasar_a(actual: Lifecycle, nuevo: Lifecycle, revisado: bool) -> str | None:
    """GA exige last_preview_at (module_not_reviewed); RETIRADO es final."""
    if actual == nuevo:
        return None
    if actual == Lifecycle.RETIRADO:
        return "module_retired"
    if nuevo == Lifecycle.GA and not revisado:
        return "module_not_reviewed"
    return None
