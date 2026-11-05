import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


class GeneradorSintetico:
    """Generador determinista de datos sintéticos para calibración y arranque en frío."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)

    def generar_series_demanda(
        self,
        num_variantes: int = 10,
        num_semanas: int = 52,
        num_sucursales: int = 3,
        fecha_inicio: datetime | None = None,
    ) -> List[Dict[str, Any]]:
        if fecha_inicio is None:
            fecha_inicio = datetime(2025, 11, 1, tzinfo=timezone.utc)

        registros: List[Dict[str, Any]] = []

        # Atributos base por variante
        variantes = []
        for i in range(num_variantes):
            precio_base = round(self.rng.uniform(80.0, 350.0), 2)
            demanda_base = self.rng.uniform(10.0, 40.0)
            elasticidad = self.rng.uniform(0.8, 1.6)
            variantes.append({
                "id": f"var-{i+1:03d}",
                "precio_base": precio_base,
                "demanda_base": demanda_base,
                "elasticidad": elasticidad,
            })

        for semana in range(1, num_semanas + 1):
            fecha_sem = fecha_inicio + timedelta(weeks=semana - 1)
            # Factor estacional anual (pico en diciembre sem 48-52 y mitad de año sem 24-26)
            factor_estacional = 1.0 + 0.35 * math.sin(2 * math.pi * semana / 52)
            if semana >= 48:
                factor_estacional += 0.45

            es_festivo = semana in [1, 7, 18, 25, 32, 45, 51, 52]

            for s_idx in range(num_sucursales):
                sucursal_id = f"suc-{s_idx+1:03d}"
                # Factor de escala por sucursal (matriz vs satélite)
                factor_sucursal = 1.2 if s_idx == 0 else 0.85

                for v in variantes:
                    en_promocion = self.rng.random() < 0.20
                    descuento = 0.20 if en_promocion else 0.0
                    precio_real = round(v["precio_base"] * (1.0 - descuento), 2)

                    # Cálculo de unidades esperadas
                    efecto_precio = (v["precio_base"] / max(precio_real, 1.0)) ** v["elasticidad"]
                    efecto_festivo = 1.25 if es_festivo else 1.0
                    efecto_promo = 1.40 if en_promocion else 1.0

                    esperadas = (
                        v["demanda_base"]
                        * factor_estacional
                        * factor_sucursal
                        * efecto_precio
                        * efecto_festivo
                        * efecto_promo
                    )

                    ruido = self.rng.gauss(0.0, max(2.0, esperadas * 0.15))
                    unidades = max(0, int(round(esperadas + ruido)))

                    registros.append({
                        "semana": semana,
                        "fecha_semana": fecha_sem.strftime("%Y-%m-%d"),
                        "variante_id": v["id"],
                        "sucursal_id": sucursal_id,
                        "precio": precio_real,
                        "es_festivo": 1 if es_festivo else 0,
                        "en_promocion": 1 if en_promocion else 0,
                        "unidades_vendidas": unidades,
                    })

        return registros

    def generar_clientes_rfm(self, num_clientes: int = 200) -> List[Dict[str, Any]]:
        """Genera perfiles RFM (Recency, Frequency, Monetary) de clientes sintéticos."""
        clientes: List[Dict[str, Any]] = []

        for i in range(num_clientes):
            # 3 perfiles típicos: VIP/Frecuente (20%), Ocasional (50%), Inactivo/Perdido (30%)
            tipo = self.rng.random()
            if tipo < 0.20:
                # VIP
                recency = self.rng.randint(1, 25)
                frequency = self.rng.randint(8, 30)
                ticket_medio = self.rng.uniform(250.0, 600.0)
            elif tipo < 0.70:
                # Ocasional
                recency = self.rng.randint(20, 120)
                frequency = self.rng.randint(2, 7)
                ticket_medio = self.rng.uniform(100.0, 300.0)
            else:
                # Inactivo / en riesgo
                recency = self.rng.randint(120, 365)
                frequency = self.rng.randint(1, 3)
                ticket_medio = self.rng.uniform(60.0, 200.0)

            monetary = round(frequency * ticket_medio, 2)
            clientes.append({
                "cliente_id": f"cli-{i+1:04d}",
                "recency_dias": recency,
                "frequency_compras": frequency,
                "monetary_total": monetary,
            })

        return clientes

    def generar_ventas_diarias_anomalias(
        self,
        num_dias: int = 90,
        num_sucursales: int = 3,
        tasa_anomalias: float = 0.05,
        fecha_inicio: datetime | None = None,
    ) -> List[Dict[str, Any]]:
        """Genera ventas diarias e inyecta anomalías controladas."""
        if fecha_inicio is None:
            fecha_inicio = datetime(2026, 8, 1, tzinfo=timezone.utc)

        registros: List[Dict[str, Any]] = []

        for d in range(num_dias):
            fecha = (fecha_inicio + timedelta(days=d)).strftime("%Y-%m-%d")
            dia_semana = (fecha_inicio + timedelta(days=d)).weekday()
            es_fin_de_semana = dia_semana in [4, 5, 6]  # Viernes, Sábado, Domingo

            for s in range(num_sucursales):
                sucursal_id = f"suc-{s+1:03d}"
                ventas_base = 3500.0 if es_fin_de_semana else 2000.0
                tx_base = 25 if es_fin_de_semana else 15

                es_anomalia = self.rng.random() < tasa_anomalias
                tipo_anomalia = None

                if es_anomalia:
                    if self.rng.random() < 0.5:
                        # Caída abrupta (corte de energía / terminal caída)
                        ventas = round(self.rng.uniform(0.0, 200.0), 2)
                        transacciones = self.rng.randint(0, 2)
                        tipo_anomalia = "CAIDA_ABRUPTA"
                    else:
                        # Pico atípico / venta masiva fraudulenta
                        ventas = round(ventas_base * self.rng.uniform(3.5, 6.0), 2)
                        transacciones = int(tx_base * self.rng.uniform(3.0, 5.0))
                        tipo_anomalia = "PICO_ATIPICO"
                else:
                    ventas = round(
                        max(500.0, self.rng.gauss(ventas_base, ventas_base * 0.15)), 2
                    )
                    transacciones = max(3, int(round(self.rng.gauss(tx_base, 3.0))))

                ticket_promedio = round(ventas / max(transacciones, 1), 2)

                registros.append({
                    "fecha": fecha,
                    "sucursal_id": sucursal_id,
                    "ventas_totales": ventas,
                    "num_transacciones": transacciones,
                    "ticket_promedio": ticket_promedio,
                    "es_anomalia": 1 if es_anomalia else 0,
                    "tipo_anomalia": tipo_anomalia,
                })

        return registros
