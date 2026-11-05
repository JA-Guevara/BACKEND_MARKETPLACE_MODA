"""Script de demostración de los 6 reportes con IA (CU-09, 8.2).

Ejecuta las 6 consultas en lenguaje natural:
1. "Mostrame las ventas de septiembre agrupadas por sucursal"
2. "¿Cuáles fueron los diez productos más vendidos este mes?"
3. "Generá un gráfico de ventas por semana"
4. "Compará las ventas de las sucursales durante los últimos tres meses"
5. "Mostrame los productos con menor existencia"
6. "¿Qué categorías generaron mayores ingresos durante este período?"
"""
import json
import os
from pathlib import Path
from datetime import date
from uuid import UUID

from src.infrastructure.database.session import SessionLocal
from src.reportes_ia.application.reportes_ia_service import ReportesIAService
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


EJEMPLOS = [
    ("1_ventas_por_sucursal", "Mostrame las ventas de septiembre agrupadas por sucursal"),
    ("2_top_productos", "¿Cuáles fueron los diez productos más vendidos este mes?"),
    ("3_ventas_por_semana", "Generá un gráfico de ventas por semana"),
    ("4_comparativa_sucursales", "Compará las ventas de las sucursales durante los últimos tres meses"),
    ("5_menor_existencia", "Mostrame los productos con menor existencia"),
    ("6_ingresos_por_categoria", "¿Qué categorías generaron mayores ingresos durante este período?"),
]


def ejecutar_demostracion(tenant_id: UUID | None = None) -> None:
    db = SessionLocal()
    try:
        if not tenant_id:
            tenant = db.query(TenantModel).first()
            if not tenant:
                print("No se encontró ningún tenant en la base de datos.")
                return
            tenant_id = tenant.id

        output_dir = Path("tmp/evidencias_ia")
        output_dir.mkdir(parents=True, exist_ok=True)

        svc = ReportesIAService(db, tenant_id)
        hoy = date.today()

        print(f"Iniciando demostración de CU-09 para tenant {tenant_id}...")

        for tag, prompt in EJEMPLOS:
            print(f"\n---> Prompt: '{prompt}'")
            # 1. Interpretar
            inter_res = svc.interpretar(prompt, canal="TEXT", hoy=hoy)
            print(f"Status interpretación: {inter_res['status']} ({inter_res.get('interpreter')})")
            spec = inter_res.get("spec")
            if not spec:
                print(f"Error interpretando: {inter_res}")
                continue

            # 2. Ejecutar
            req_id = UUID(inter_res["request_id"]) if "request_id" in inter_res else None
            rep = svc.ejecutar(spec, request_id=req_id)
            print(f"Reporte: {rep['title']} | Filas: {len(rep['rows'])}")
            print(f"Narrativa: {rep['narrative']}")

            # Guardar JSON
            json_path = output_dir / f"{tag}.json"
            json_path.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

            # 3. Exportar XLSX
            xlsx_bytes, _, _ = svc.exportar(spec, formato="xlsx", request_id=req_id)
            xlsx_path = output_dir / f"{tag}.xlsx"
            xlsx_path.write_bytes(xlsx_bytes)

            # 4. Exportar PDF
            pdf_bytes, _, _ = svc.exportar(spec, formato="pdf", request_id=req_id)
            pdf_path = output_dir / f"{tag}.pdf"
            pdf_path.write_bytes(pdf_bytes)

            print(f"Guardado: {json_path.name}, {xlsx_path.name}, {pdf_path.name}")

        print("\nDemostración de CU-09 completada con éxito.")
    finally:
        db.close()


if __name__ == "__main__":
    ejecutar_demostracion()
