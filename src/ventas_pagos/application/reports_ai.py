"""Inteligencia (opcional) para el modulo de reportes.

Funcionalidad A (interpretar): convierte una consulta en lenguaje natural a una
estructura validada (vista, filtros, agrupacion, metrica, comparacion) sin tocar
datos. Los nombres se resuelven contra el catalogo autorizado de forma
determinista; nunca confia en IDs que arriesgue el modelo.

Funcionalidad B (explicar): dado el contexto de filtros visibles, el servidor
RECALCULA las metricas con ReportsService y el LLM produce hallazgo/cifras/
interpretacion/accion/limitaciones.

Si IA no esta configurada o falla, el dashboard sigue funcionando: ambas
funciones devuelven available=False con mensaje accionable.
"""
import json
import re
import uuid
from datetime import datetime, timedelta

import httpx

from src.infrastructure.config.settings import settings
from src.ventas_pagos.application.reports_service import BUSINESS_TZ, ReportsService
from src.ventas_pagos.web.schemas import ReportFilters


def _chat(system: str, content: str, max_tokens: int = 350) -> str:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + settings.ai_api_key},
        json={
            "model": settings.ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_tokens": min(max_tokens, settings.ai_max_tokens),
            "temperature": 0.2,
        },
        timeout=settings.ai_timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


class ReportsAI:
    def __init__(self, db) -> None:
        self.db = db

    # ---------- Funcion A: interpretar consulta ----------

    def interpret(self, message: str, current: ReportFilters | None, catalog: dict) -> dict:
        text = self._normalize(message)
        result = {
            "ok": True,
            "vista": "resumen",
            "filtros": {"branch_id": None, "category_id": None, "date_from": None, "date_to": None, "status": None},
            "agrupacion": None,
            "metrica": "revenue",
            "comparacion": "none",
            "aclaraciones": [],
            "respuesta": "",
        }

        # Contexto visible del dashboard: pedidos como "explicame esto" o
        # "exportá esto" reutilizan los filtros que la pantalla ya está
        # mostrando. Lo que el texto pida explícitamente (periodo, sucursal
        # nombrada, categoría) gana después sobre estos valores de arranque.
        if current and re.search(r"esto|este (?:contexto|tablero)|lo que veo|en pantalla|de la vista|visible|actual|esta ventana|de aqui", text):
            if current.branch_id:
                result["filtros"]["branch_id"] = str(current.branch_id)
            if current.category_id:
                result["filtros"]["category_id"] = str(current.category_id)
            if current.status:
                result["filtros"]["status"] = current.status
            if current.date_from:
                result["filtros"]["date_from"] = current.date_from.isoformat()
            if current.date_to:
                result["filtros"]["date_to"] = current.date_to.isoformat()
            result["aclaraciones"].append("Usé los filtros visibles del dashboard como punto de partida.")

        # Periodo.
        try:
            period, day = self._period(text)
        except ValueError as error:
            result['ok'] = False
            result['aclaraciones'].append(str(error))
            result['respuesta'] = str(error)
            return result
        if period:
            result["filtros"]["date_from"], result["filtros"]["date_to"] = period
        result["comparacion"] = self._comparison(text, day)

        # Metrica.
        metrica = self._metric(text)
        result["metrica"] = metrica
        if metrica == "low_stock":
            result["vista"] = "productos_inventario"
        elif metrica == "reservations":
            result["vista"] = "reservas"

        # Sucursal(es) nominales. Se comparan nombres normalizados (sin
        # mayusculas ni tildes) contra el texto de la consulta.
        branches = [b for b in catalog.get("branches", []) if self._normalize(b["name"]) in text]
        if len(branches) == 1:
            result["filtros"]["branch_id"] = branches[0]["id"]
        elif len(branches) > 1:
            result['ok'] = False
            result["aclaraciones"].append("Encontre varias sucursales con ese nombre; elegí una para filtrar.")
        elif re.search(r"\b(?:sucursal|local|tienda de)\s+(?!actual\b|seleccionada\b|visible\b)\w+", text) and not re.search(r"por (?:sucursal|local)|todas las sucursales|sin sucursal|(?:quita|limpia|elimina).*sucursal", text):
            result['ok'] = False
            result["aclaraciones"].append("No encontre esa sucursal en los datos autorizados; no puedo filtrar por ella.")

        # Categoria nominal.
        categories = [c for c in catalog.get("categories", []) if self._normalize(c["name"]) in text]
        if len(categories) == 1:
            result["filtros"]["category_id"] = categories[0]["id"]
        elif len(categories) > 1:
            result['ok'] = False
            result["aclaraciones"].append("Encontre varias categorias coincidentes; elegí una.")
        elif re.search(r"\bcategoria\s+(?!actual\b|seleccionada\b|visible\b)\w+", text) and not re.search(r"por categoria|sin categoria|(?:quita|limpia|elimina).*categoria", text):
            result['ok'] = False
            result['aclaraciones'].append('No encontre esa categoria en el catalogo; indicá su nombre antes de aplicar el filtro.')

        if re.search(r"pendiente|sin pagar|por pagar", text):
            result["filtros"]["status"] = "pending_payment"
        elif re.search(r"cobrados?|pagad", text):
            result["filtros"]["status"] = 'paid'
        else:
            for pattern, status in ((r'cancelad', 'cancelled'), (r'entregad', 'delivered'),
                                    (r'enviad|en camino', 'shipped'), (r'en preparacion|procesando', 'processing'),
                                    (r'expirad|vencid', 'expired')):
                if re.search(pattern, text):
                    result['filtros']['status'] = status
                    break

        # Agrupacion.
        result["agrupacion"] = self._grouping(text)
        if result["agrupacion"] == "sucursal":
            result["vista"] = "sucursales"
        elif result["agrupacion"] in {"categoria", "diario", "mensual", "hora"}:
            result["vista"] = "comparativas"
        if result["comparacion"] != "none" and result["metrica"] != "low_stock":
            result["vista"] = "comparativas"

        result["respuesta"] = self._summary(result, catalog)
        return result

    @staticmethod
    def _normalize(text: str) -> str:
        accents = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
        normalized = "".join(accents.get(ch, ch) for ch in text.lower())
        return " " + normalized + " "

    def _period(self, text: str) -> tuple[tuple[str, str], str] | tuple[None, str]:
        now = datetime.now(BUSINESS_TZ)
        today = now.date()
        iso_from = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S")
        dates = re.findall(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b', text)
        if dates:
            if len(dates) > 2:
                raise ValueError('Indicá como máximo una fecha inicial y una final.')
            try:
                parsed = [datetime.strptime(value, '%Y-%m-%d' if '-' in value else '%d/%m/%Y').date() for value in dates]
            except ValueError:
                raise ValueError('La fecha no es válida. Usá DD/MM/AAAA o AAAA-MM-DD.')
            first, last = parsed[0], parsed[-1]
            if first > last:
                raise ValueError('La fecha inicial no puede ser posterior a la final.')
            return (iso_from(datetime.combine(first, datetime.min.time())), iso_from(datetime.combine(last, datetime.max.time()))), 'explicit'
        if re.search(r"hoy", text):
            return (iso_from(datetime.combine(today, datetime.min.time())), iso_from(datetime.combine(today, datetime.max.time()))), "today"
        if re.search(r"ayer", text):
            day = today - timedelta(days=1)
            return (iso_from(datetime.combine(day, datetime.min.time())), iso_from(datetime.combine(day, datetime.max.time()))), "yesterday"
        match = re.search(r"(?:ultimos|ultimos) (\d+) (dia|dias|semana|semanas|mes|meses)", text)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            days = value * (30 if unit.startswith("mes") else 7 if unit.startswith("sema") else 1)
            if not 1 <= days <= 3660:
                raise ValueError('El período debe estar entre 1 día y 10 años.')
            start = iso_from(datetime.combine(today - timedelta(days=days - 1), datetime.min.time()))
            return (start, iso_from(now)), "last_days"
        if re.search(r"mes actual|este mes", text):
            return (iso_from(datetime.combine(today.replace(day=1), datetime.min.time())), iso_from(now)), "month"
        if re.search(r"mes pasado|mes anterior|ultimo mes", text):
            first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            last = today.replace(day=1) - timedelta(days=1)
            return (iso_from(datetime.combine(first, datetime.min.time())), iso_from(datetime.combine(last, datetime.max.time()))), "last_month"
        if re.search(r"ano actual|este ano|ano en curso|año", text):
            return (iso_from(datetime.combine(today.replace(month=1, day=1), datetime.min.time())), iso_from(now)), "year"
        return None, "none"

    @staticmethod
    def _comparison(text: str, day: str) -> str:
        if re.search(r"ano pasado|hace un ano|vs el ano", text):
            return "year_ago"
        if re.search(r"anterior|previo|respecto (a|al)|comparar|vs ", text) or "vs" in text:
            return "previous"
        return "none"

    @staticmethod
    def _metric(text: str) -> str:
        if re.search(r"stock bajo|existencia baja|falta stock|faltan existencias|quedan pocas|por reponer", text):
            return "low_stock"
        if re.search(r"unidades|prendas vendidas|cantidad vendida|vendidas", text):
            return "units"
        if re.search(r"ticket|promedio de venta|promedio", text):
            return "ticket"
        if re.search(r"reserva", text):
            return "reservations"
        if re.search(r"pedido|orden|ordenes|compras registradas", text):
            return "orders"
        return "revenue"

    @staticmethod
    def _grouping(text: str) -> str | None:
        if re.search(r"por categoria|por prenda", text):
            return "categoria"
        if re.search(r"por sucursal|por local|por tienda", text):
            return "sucursal"
        if re.search(r"por dia|diario", text):
            return "diario"
        if re.search(r"por mes|mensual", text):
            return "mensual"
        if re.search(r"por hora", text):
            return "hora"
        return None

    def _summary(self, result: dict, catalog: dict) -> str:
        metric_label = {
            "revenue": "ingresos cobrados",
            "units": "unidades vendidas",
            "orders": "pedidos creados",
            "ticket": "ticket promedio",
            "low_stock": "variantes con stock bajo",
            "reservations": "reservas",
        }[result["metrica"]]
        part = metric_label
        group = {"categoria": "por categoría", "sucursal": "por sucursal", "diario": "por día",
                 "mensual": "por mes", "hora": "por hora"}.get(result["agrupacion"])
        if group:
            part += f" {group}"
        branch = next((b for b in catalog.get("branches", []) if b["id"] == result["filtros"]["branch_id"]), None)
        category = next((c for c in catalog.get("categories", []) if c["id"] == result["filtros"]["category_id"]), None)
        if branch:
            part += f" · sucursal {branch['name']}"
        if category:
            part += f" · categoría {category['name']}"
        if result["filtros"]["status"] == "pending_payment":
            part += " · solo pendientes de pago"
        comp = {"previous": " comparado con el período anterior", "year_ago": " comparado con el año pasado"}.get(result["comparacion"], "")
        part += comp
        return f"Mostrar {part}."

    # ---------- Funcion B: explicar metricas ----------

    def explain(self, question: str, filters: ReportFilters) -> dict:
        context = self._snapshot(filters)
        if not settings.ai_api_key:
            return {
                "available": False,
                "message": "La IA no esta configurada. Las metricas reales ya estan disponibles en el dashboard.",
                "context_used": self._context_used(filters),
            }
        try:
            content = _chat(
                "Sos analista comercial de FashionStore. Responde SOLO en JSON con estas claves: "
                'hallazgo (string), cifras (string), interpretacion (string), accion (string), limitaciones (string). '
                "No inventes datos ni causalidad; usa solo el contexto. Si faltan datos para la pregunta, "
                "decilo en limitaciones.",
                f"Contexto real del reporte:\n{context}\n\nPregunta del usuario: {question}",
                max_tokens=450,
            )
            payload = json.loads(content)
            if not isinstance(payload, dict) or not all(isinstance(value, str) for value in payload.values()):
                raise ValueError('Respuesta de IA no estructurada.')
            sections = {
                "hallazgo": payload.get("hallazgo", ""),
                "cifras": payload.get("cifras", ""),
                "interpretacion": payload.get("interpretacion", ""),
                "accion": payload.get("accion", ""),
                "limitaciones": payload.get("limitaciones", ""),
            }
            return {"available": True, "sections": sections, "context_used": self._context_used(filters)}
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            return {
                "available": False,
                "message": "El servicio de IA no respondio de forma util. Puede continuar con las metricas reales.",
                "context_used": self._context_used(filters),
            }

    def _snapshot(self, filters: ReportFilters) -> str:
        data = ReportsService(self.db).dashboard(
            date_from=filters.date_from, date_to=filters.date_to,
            branch_id=filters.branch_id, category_id=filters.category_id, status=filters.status,
            low_stock_lt=filters.low_stock_lt,
        )
        compact = {
            "periodo": data["meta"]["period"],
            "zona": data["meta"]["timezone"],
            "moneda": data["currency"],
            "pedidos_en_periodo": data["period"]["orders"],
            "pagados": data["period"]["paid_orders"],
            "pendientes": data["period"]["pending_orders"],
            "ingresos": data["period"]["revenue"],
            "unidades": data["period"]["units_sold"],
            "ticket": data["period"]["ticket_avg"],
            "por_estado": data["by_status"],
            "comparacion_periodo_anterior": data["comparison"]["previous"] if data["comparison"]["available"] else None,
            "top_prendas": data["top_products"],
            "por_categoria": data["category_breakdown"],
            "por_sucursal": data["branch_performance"],
            "metodos_pago": data["payment_methods"],
            "reservas_por_estado": data["reservations_by_status"],
            "stock_bajo": data["low_stock_variants"],
        }
        return json.dumps(compact, ensure_ascii=False, default=str)

    @staticmethod
    def _context_used(filters: ReportFilters) -> dict:
        return {
            "date_from": filters.date_from.isoformat() if filters.date_from else None,
            "date_to": filters.date_to.isoformat() if filters.date_to else None,
            "branch_id": str(filters.branch_id) if filters.branch_id else None,
            "category_id": str(filters.category_id) if filters.category_id else None,
            "status": filters.status,
            "low_stock_lt": filters.low_stock_lt,
        }
