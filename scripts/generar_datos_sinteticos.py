#!/usr/bin/env python3
"""CLI para generar datos sintéticos y calibrar modelos de Machine Learning (CU-10)."""

import argparse
import json
import sys
from pathlib import Path

# Añadir raíz al sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analitica_ml.domain.sinteticos import GeneradorSintetico


def main() -> None:
    parser = argparse.ArgumentParser(description="Generador determinista de datos sintéticos ML")
    parser.add_argument("--tipo", choices=["demanda", "rfm", "anomalias", "todos"], default="todos")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--salida", type=str, default="storage/datos_sinteticos")
    args = parser.parse_args()

    gen = GeneradorSintetico(seed=args.seed)
    out_dir = Path(args.salida)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.tipo in ["demanda", "todos"]:
        datos = gen.generar_series_demanda(num_variantes=10, num_semanas=52, num_sucursales=3)
        path = out_dir / "series_demanda.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
        print(f"Generadas {len(datos)} observaciones de demanda en {path}")

    if args.tipo in ["rfm", "todos"]:
        datos = gen.generar_clientes_rfm(num_clientes=200)
        path = out_dir / "clientes_rfm.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
        print(f"Generados {len(datos)} perfiles RFM en {path}")

    if args.tipo in ["anomalias", "todos"]:
        datos = gen.generar_ventas_diarias_anomalias(num_dias=90, num_sucursales=3)
        path = out_dir / "ventas_anomalias.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
        print(f"Generadas {len(datos)} ventas diarias con anomalías en {path}")


if __name__ == "__main__":
    main()
