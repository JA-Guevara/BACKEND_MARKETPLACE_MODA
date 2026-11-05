"""Reglas puras de promociones y ofertas (CU-11).

No interactúa con la base de datos ni con frameworks; calcula precios,
valida coherencia de fechas y valores (paso 6a), calcula estado y vigencia (7a).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class OfertaAplicada:
    promotion_id: str
    name: str
    discount_type: str
    discount_value: Decimal
    regular_price: Decimal
    final_price: Decimal
    ends_at: datetime | None


def precio_final(regular: Decimal, tipo: str, valor: Decimal) -> Decimal:
    """Calcula el precio final con dos decimales según el tipo de oferta."""
    regular = Decimal(str(regular))
    valor = Decimal(str(valor))
    if tipo == "percent":
        factor = max(Decimal(0), Decimal(100) - valor) / Decimal(100)
        res = regular * factor
    elif tipo == "fixed":
        res = max(Decimal(0), regular - valor)
    elif tipo == "clearance":
        res = max(Decimal(0), valor)
    elif tipo == "free_shipping":
        res = regular
    else:
        res = regular
    return res.quantize(CENT, rounding=ROUND_HALF_UP)


def validar(
    tipo: str,
    valor: Decimal,
    inicio: datetime | None,
    fin: datetime | None,
    regulares: list[Decimal],
) -> list[str]:
    """6a: valida coherencia de la oferta contra los precios regulares alcanzados."""
    errores: list[str] = []
    valor = Decimal(str(valor))

    if tipo in ("percent", "fixed", "clearance") and valor <= 0:
        errores.append("El valor del descuento debe ser mayor a cero.")

    if tipo == "percent" and valor > 90:
        errores.append("El porcentaje de descuento no puede superar el 90%.")

    if inicio and fin and fin <= inicio:
        errores.append("La fecha de fin debe ser posterior a la de inicio.")

    if regulares and tipo in ("percent", "fixed", "clearance"):
        for regular in regulares:
            reg = Decimal(str(regular))
            final = precio_final(reg, tipo, valor)
            if final <= 0:
                errores.append(
                    f"El precio final resultante (Bs {final}) no puede ser menor o igual a cero para el precio regular Bs {reg}."
                )
                break
            if tipo != "clearance" and final >= reg:
                errores.append(
                    f"El descuento debe reducir el precio regular (Bs {reg} -> Bs {final})."
                )
                break

    return errores


def vigente_en(p: Any, momento: datetime | None = None) -> bool:
    """Comprueba si la oferta estaba o está vigente en un momento dado (base de 7a)."""
    if momento is None:
        momento = datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)

    # Debe estar activa
    if not getattr(p, "is_active", True):
        return False

    # Si fue desactivada manualmente antes del momento evaluado
    deactivated_at = getattr(p, "deactivated_at", None)
    if deactivated_at is not None:
        if deactivated_at.tzinfo is None:
            deactivated_at = deactivated_at.replace(tzinfo=timezone.utc)
        if momento >= deactivated_at:
            return False

    # Vigencia temporal
    starts_at = getattr(p, "starts_at", None)
    if starts_at is not None:
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if momento < starts_at:
            return False

    ends_at = getattr(p, "ends_at", None)
    if ends_at is not None:
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if momento >= ends_at:
            return False

    return True


def estado(p: Any, ahora: datetime | None = None) -> Literal["ACTIVA", "PROGRAMADA", "VENCIDA", "INACTIVA", "AGOTADA"]:
    """Calcula el estado visual de la oferta según sus límites y vigencia."""
    if ahora is None:
        ahora = datetime.now(timezone.utc)
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=timezone.utc)

    if not getattr(p, "is_active", True):
        return "INACTIVA"

    deactivated_at = getattr(p, "deactivated_at", None)
    if deactivated_at is not None:
        if deactivated_at.tzinfo is None:
            deactivated_at = deactivated_at.replace(tzinfo=timezone.utc)
        if ahora >= deactivated_at:
            return "INACTIVA"

    max_uses = getattr(p, "max_uses", None)
    uses_count = getattr(p, "uses_count", 0)
    if max_uses is not None and uses_count >= max_uses:
        return "AGOTADA"

    starts_at = getattr(p, "starts_at", None)
    if starts_at is not None:
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if ahora < starts_at:
            return "PROGRAMADA"

    ends_at = getattr(p, "ends_at", None)
    if ends_at is not None:
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ahora >= ends_at:
            return "VENCIDA"

    return "ACTIVA"


def alcanza(p: Any, variante: Any) -> bool:
    """Verifica si la promoción alcanza a una variante específica."""
    targets = getattr(p, "targets", None)
    if targets:
        var_id = getattr(variante, "id", None)
        prod_id = getattr(variante, "product_id", None)
        product = getattr(variante, "product", None)
        cat_id = getattr(variante, "category_id", getattr(product, "category_id", None))
        season_id = getattr(variante, "season_id", getattr(product, "season_id", None))
        collection_id = getattr(variante, "collection_id", getattr(product, "collection_id", None))

        matched = False
        for t in targets:
            ttype = getattr(t, "target_type", "")
            tid = getattr(t, "target_id", None)
            if ttype == "ALL":
                matched = True
                break
            if ttype == "VARIANT" and var_id and str(var_id) == str(tid):
                matched = True
                break
            if ttype == "PRODUCT" and prod_id and str(prod_id) == str(tid):
                matched = True
                break
            if ttype == "CATEGORY" and cat_id and str(cat_id) == str(tid):
                matched = True
                break
            if ttype == "SEASON" and season_id and str(season_id) == str(tid):
                matched = True
                break
            if ttype == "COLLECTION" and collection_id and str(collection_id) == str(tid):
                matched = True
                break
        return matched

    # Fallback legacy: category_id / product_id directos en PromotionModel
    p_cat = getattr(p, "category_id", None)
    p_prod = getattr(p, "product_id", None)

    if p_cat:
        cat_id = getattr(variante, "category_id", None)
        if not cat_id and getattr(variante, "product", None):
            cat_id = getattr(variante.product, "category_id", None)
        return str(cat_id) == str(p_cat)

    if p_prod:
        prod_id = getattr(variante, "product_id", None)
        return str(prod_id) == str(p_prod)

    # Si no tiene targets ni filtros de categoría/producto, alcanza a todo el catálogo
    return True


def mejor_automatica(
    ofertas: list[Any],
    variante: Any,
    canal: Literal["ONLINE", "POS", "OFFLINE"] = "ONLINE",
    ahora: datetime | None = None,
) -> OfertaAplicada | None:
    """Busca la mejor campaña automática para la variante en el canal y momento dados.

    Solo evalúa ofertas automáticas (sin código), vigentes y asignadas al canal.
    No se apilan: elige la que arroja el menor precio final.
    """
    if ahora is None:
        ahora = datetime.now(timezone.utc)

    # Obtener precio regular
    regular = getattr(variante, "price_override", None)
    if regular is None and getattr(variante, "product", None):
        regular = getattr(variante.product, "base_price", Decimal(0))
    if regular is None:
        regular = getattr(variante, "base_price", Decimal(0))
    regular = Decimal(str(regular)).quantize(CENT)

    aplicables: list[tuple[Decimal, Any]] = []

    for p in ofertas:
        # Solo automáticas (sin cupón)
        if getattr(p, "code", None):
            continue

        # Canal
        if canal == "ONLINE" and not getattr(p, "applies_online", True):
            continue
        if canal == "POS" and not getattr(p, "applies_pos", True):
            continue
        if canal == "OFFLINE" and not getattr(p, "applies_offline", False):
            continue

        # Vigencia
        if not vigente_en(p, ahora):
            continue

        # Alcance
        if not alcanza(p, variante):
            continue

        p_final = precio_final(regular, p.discount_type, p.discount_value)
        # La oferta solo aplica si efectivamente descuenta el precio (salvo free_shipping)
        if p_final < regular or p.discount_type == "clearance":
            aplicables.append((p_final, p))

    if not aplicables:
        return None

    # Elegir la que deja el menor precio final
    aplicables.sort(key=lambda x: x[0])
    best_final, best_promo = aplicables[0]

    return OfertaAplicada(
        promotion_id=str(best_promo.id),
        name=best_promo.name,
        discount_type=best_promo.discount_type,
        discount_value=Decimal(str(best_promo.discount_value)),
        regular_price=regular,
        final_price=best_final,
        ends_at=getattr(best_promo, "ends_at", None),
    )
