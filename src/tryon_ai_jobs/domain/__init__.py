"""Estados del trabajo de foto IA realista (plan de evolución, Fase 3)."""

# La generación corre en segundo plano: la petición de crear el trabajo vuelve
# rápido y quien lo pide consulta el estado cuando quiere.
ESTADO_ENCUESTO = "queued"
ESTADO_PROCESANDO = "processing"
ESTADO_LISTO = "ready"
ESTADO_FALLIDO = "failed"
ESTADO_CANCELADO = "cancelled"
ESTADO_EXPIRADO = "expired"

# Estados en los que el trabajo todavía puede evolucionar.
ACTIVOS = {ESTADO_ENCUESTO, ESTADO_PROCESANDO}

TERMINALES = {ESTADO_LISTO, ESTADO_FALLIDO, ESTADO_CANCELADO, ESTADO_EXPIRADO}