from typing import Any, Dict, List, Tuple
import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.metrics import silhouette_score


class ModeloDemanda:
    """Modelo de pronóstico de demanda basado en Gradient Boosting."""

    def __init__(self, n_estimators: int = 100, max_depth: int = 4, random_state: int = 42) -> None:
        self.modelo = GradientBoostingRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=random_state,
            learning_rate=0.08,
            subsample=0.85,
        )
        self.entrenado = False
        self.feature_names: List[str] = []

    def entrenar(self, X: np.ndarray, y: np.ndarray, feature_names: List[str] | None = None) -> None:
        self.modelo.fit(X, y)
        self.entrenado = True
        self.feature_names = feature_names or []

    def predecir(self, X: np.ndarray) -> np.ndarray:
        if not self.entrenado:
            raise RuntimeError("El modelo de demanda no está entrenado.")
        pred = self.modelo.predict(X)
        return np.maximum(0.0, pred)  # Unidades nunca pueden ser negativas


class ModeloSectorizacionRFM:
    """Clustering KMeans para segmentación de clientes con etiquetado semántico."""

    def __init__(self, k_fijo: int | None = None, random_state: int = 42) -> None:
        self.k_fijo = k_fijo
        self.random_state = random_state
        self.modelo: KMeans | None = None
        self.n_clusters_: int = 3
        self.labels_semanticos_: Dict[int, str] = {}
        self.silhouette_score_: float = 0.0

    def seleccionar_k_optimo(self, X: np.ndarray, k_min: int = 2, k_max: int = 5) -> int:
        mejor_k = k_min
        mejor_silueta = -1.0
        for k in range(k_min, min(k_max + 1, len(X))):
            km = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
            labels = km.fit_predict(X)
            if len(set(labels)) > 1:
                sil = silhouette_score(X, labels)
                if sil > mejor_silueta:
                    mejor_silueta = sil
                    mejor_k = k
        self.silhouette_score_ = mejor_silueta
        return mejor_k

    def entrenar(self, X: np.ndarray, clientes_raw: List[Dict[str, Any]]) -> None:
        if self.k_fijo:
            k = self.k_fijo
            km = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
            labels = km.fit_predict(X)
            self.silhouette_score_ = silhouette_score(X, labels) if len(set(labels)) > 1 else 0.0
        else:
            k = self.seleccionar_k_optimo(X, k_min=2, k_max=4)
            km = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
            labels = km.fit_predict(X)

        self.modelo = km
        self.n_clusters_ = k

        # Asignar nombres semánticos a cada cluster según sus centroides raw
        # (Recency bajo + Monetary alto = VIP; Recency alto = En Riesgo; etc.)
        cluster_metricas: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(k)}
        for idx, lbl in enumerate(labels):
            cluster_metricas[lbl].append(clientes_raw[idx])

        # Calcular promedios por cluster
        promedios = {}
        for c_id, grupo in cluster_metricas.items():
            if grupo:
                avg_r = sum(c["recency_dias"] for c in grupo) / len(grupo)
                avg_m = sum(c["monetary_total"] for c in grupo) / len(grupo)
                promedios[c_id] = (avg_r, avg_m)
            else:
                promedios[c_id] = (999.0, 0.0)

        # Ordenar clusters: menor recency y mayor monetary primero
        clusters_ordenados = sorted(promedios.keys(), key=lambda cid: (-promedios[cid][1], promedios[cid][0]))

        nombres_disponibles = ["VIP / Clientes Estrella", "Frecuentes / Leales", "Ocasionales", "En Riesgo / Inactivos"]
        self.labels_semanticos_ = {}
        for rank, cid in enumerate(clusters_ordenados):
            nombre = nombres_disponibles[min(rank, len(nombres_disponibles) - 1)]
            self.labels_semanticos_[cid] = nombre

    def predecir(self, X: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        if self.modelo is None:
            raise RuntimeError("El modelo RFM no está entrenado.")
        clusters = self.modelo.predict(X)
        nombres = [self.labels_semanticos_.get(c, f"Cluster {c}") for c in clusters]
        return clusters, nombres


class ModeloDetectorAnomalias:
    """Detección de valores atípicos y fraude usando Isolation Forest."""

    def __init__(self, contaminacion: float = 0.05, random_state: int = 42) -> None:
        self.contaminacion = contaminacion
        self.random_state = random_state
        self.modelo = IsolationForest(
            contamination=contaminacion,
            random_state=random_state,
        )
        self.entrenado = False

    def entrenar(self, X: np.ndarray) -> None:
        self.modelo.fit(X)
        self.entrenado = True

    def predecir(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Retorna:
        - es_anomalia: array booleano (True para anomalía)
        - scores: score normalizado de anomalía (menor = más anómalo)
        """
        if not self.entrenado:
            raise RuntimeError("El detector de anomalías no está entrenado.")
        preds = self.modelo.predict(X)  # -1 es anómalo, 1 es normal
        scores = self.modelo.decision_function(X)
        es_anomalia = preds == -1
        return es_anomalia, scores
