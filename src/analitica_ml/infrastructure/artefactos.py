import os
from pathlib import Path
from typing import Any
import joblib


class GestorArtefactosML:
    """Gestiona la persistencia de modelos entrenados en disco."""

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir is None:
            # storage/ml_models relativo a la raíz del backend
            base_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "storage",
                "ml_models",
            )
        self.base_dir = Path(base_dir)

    def guardar_modelo(self, tenant_id: str | Any, model_id: str, obj: Any) -> str:
        tenant_dir = self.base_dir / str(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        file_path = tenant_dir / f"{model_id}.joblib"
        joblib.dump(obj, file_path)
        return str(file_path)

    def cargar_modelo(self, file_path: str) -> Any:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Archivo de modelo no encontrado en {file_path}")
        return joblib.load(path)
