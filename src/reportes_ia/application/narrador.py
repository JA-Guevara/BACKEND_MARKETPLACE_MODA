from typing import Any
from src.infrastructure.services.ai_client import AIService
from src.reportes_ia.application.ejecutor import ReportResult
from src.reportes_ia.domain.especificacion import ReportSpec


class Narrador:
    def narrar(self, spec: ReportSpec, result: ReportResult) -> str:
        if not result.rows:
            return f"No se registraron movimientos para el reporte '{result.title}' en el período seleccionado."

        if AIService.is_configured():
            try:
                prompt = (
                    f"Redacta un resumen ejecutivo de máximo 2 oraciones en español para este reporte retail:\n"
                    f"Reporte: {result.title}\n"
                    f"Totales: {result.totals}\n"
                    f"Fila destacada: {result.rows[0] if result.rows else {}}\n"
                )
                ai_text = AIService.generate(
                    prompt=prompt,
                    system_instruction="Sé conciso, profesional y directo.",
                    max_tokens=120,
                    timeout=5,
                )
                if ai_text and len(ai_text.strip()) > 10:
                    return ai_text.strip()
            except Exception:
                pass

        first_row = result.rows[0]
        code = result.definition_code

        if code == "ventas_por_sucursal":
            top_b = first_row.get("branch", "N/A")
            top_rev = first_row.get("revenue", 0.0)
            tot_rev = result.totals.get("revenue", 0.0)
            tot_ord = result.totals.get("orders", 0)
            return (
                f"La sucursal líder del período es '{top_b}' con Bs {top_rev:,.2f} recaudados. "
                f"En total se alcanzaron Bs {tot_rev:,.2f} distribuidos en {tot_ord} pedidos registrados."
            )

        elif code == "top_productos":
            top_p = first_row.get("product", "N/A")
            top_u = first_row.get("units", 0)
            tot_u = result.totals.get("units", 0)
            branch_info = f" en la sucursal '{first_row.get('branch')}'" if "branch" in first_row else ""
            return (
                f"El artículo más vendido es '{top_p}'{branch_info} con {top_u} unidades. "
                f"Entre los principales productos se comercializó un total de {tot_u} unidades."
            )

        elif code == "pedidos":
            tot_o = result.totals.get("orders", 0)
            top_st = first_row.get("status", "N/A")
            return (
                f"Volumen total de {tot_o} pedidos registrados en el período. "
                f"El estado predominante es '{top_st}' con {first_row.get('orders', 0)} pedidos."
            )

        elif code == "ventas_por_semana":
            tot_rev = result.totals.get("revenue", 0.0)
            n_sem = len(result.rows)
            return (
                f"Evolución registrada a lo largo de {n_sem} semanas con una recaudación acumulada de Bs {tot_rev:,.2f}. "
                f"La semana de mayor ingreso fue '{first_row.get('week')}'."
            )

        elif code == "comparativa_sucursales":
            tot_rev = result.totals.get("total", 0.0)
            return (
                f"Comparativa consolidada entre {len(result.rows)} sucursales. "
                f"La mayor facturación acumulada corresponde a '{first_row.get('branch')}' dentro de un total de Bs {tot_rev:,.2f}."
            )

        elif code == "menor_existencia":
            top_p = first_row.get("product", "N/A")
            top_s = first_row.get("stock", 0)
            return (
                f"Se detectaron {len(result.rows)} artículos con inventario por debajo del umbral. "
                f"El caso más crítico es '{top_p}' con apenas {top_s} unidades disponibles."
            )

        elif code == "ingresos_por_categoria":
            top_c = first_row.get("category", "N/A")
            top_pct = first_row.get("percentage", 0.0)
            tot_rev = result.totals.get("revenue", 0.0)
            return (
                f"La categoría predominante es '{top_c}', representando el {top_pct}% de los ingresos totales (Bs {tot_rev:,.2f})."
            )

        tot = result.totals.get("revenue") or result.totals.get("orders") or len(result.rows)
        return f"Reporte '{result.title}' procesado con éxito con un total consolidado de {tot}."
