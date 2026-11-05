# Modelos de Machine Learning (CU-10)

Este documento detalla la arquitectura, características y políticas de publicación de los modelos de Machine Learning implementados en FashionStore.

## 1. Modelo de Pronóstico de Demanda Semanal

* **Algoritmo**: `GradientBoostingRegressor` (scikit-learn)
* **Objetivo**: Predecir unidades vendidas semanales por variante de producto y sucursal.
* **Características**:
  * Autoregresivas: `lag_1`, `lag_2`, `lag_3`, `lag_4` (unidades vendidas en semanas previas).
  * Estadísticas de ventana: media móvil de 4 semanas (`media_movil_4`), tendencia (`lag_1 - lag_4`).
  * Estacionales: codificación sinusoidal y cosinusoidal del número de semana anual (`sin_semana`, `cos_semana`).
  * Exógenas: `precio`, bandera de festivo (`es_festivo`), bandera de promoción (`en_promocion`).
  * Categorías: One-Hot Encoding de `variante_id` y `sucursal_id`.
* **Métricas de evaluación**:
  * MAE (Mean Absolute Error)
  * RMSE (Root Mean Squared Error)
  * MAPE (Mean Absolute Percentage Error)
  * $R^2$ (Coeficiente de determinación)
* **Regla de publicación**: Un modelo candidato se publica automáticamente si su MAE es menor o igual al 95% del baseline (o no empeora más de un margen del 5% frente al modelo activo).

---

## 2. Segmentación de Clientes (RFM)

* **Algoritmo**: `KMeans` (scikit-learn)
* **Objetivo**: Agrupar clientes según sus patrones de compra para personalizar promociones y retención.
* **Métricas RFM**:
  * **R (Recency)**: Días transcurridos desde la última compra.
  * **F (Frequency)**: Cantidad total de pedidos realizados.
  * **M (Monetary)**: Monto total gastado acumulado.
* **Preprocesamiento**: Transformación logarítmica $\log(1 + x)$ para estabilizar sesgos en frecuencia y monto, seguida de escalado estandarizado (`StandardScaler`).
* **Selección de $k$**: Coeficiente de Silueta (`silhouette_score`) evaluado entre $k=2$ y $k=5$.
* **Etiquetado Semántico**:
  * *VIP / Clientes Estrella*: Alta frecuencia y alto monto con baja recencia.
  * *Frecuentes / Leales*: Frecuencia y monto moderado-alto.
  * *Ocasionales*: Frecuencia media y montos habituales.
  * *En Riesgo / Inactivos*: Alta recencia (>90 días) con compras pasadas estancadas.

---

## 3. Detección de Anomalías en Ventas

* **Algoritmo**: `IsolationForest` (scikit-learn)
* **Objetivo**: Detectar caídas atípicas de ventas (fallas de sistema, cortes de luz) o picos desproporcionados (fraude de volumen o errores de digitación).
* **Parámetros**: Contaminación esperada del 5% (`contamination=0.05`).
* **Flujo**: Genera alertas con score de anomalía y detalle de transacciones para revisión del administrador de tienda.
