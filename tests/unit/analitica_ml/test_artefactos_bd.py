import os
import shutil

import numpy as np
import pytest

from src.analitica_ml.application.entrenamiento_service import EntrenamientoService
from src.analitica_ml.infrastructure.artefactos import (
    ArtefactoDemasiadoGrande,
    GestorArtefactosML,
    MAX_ARTIFACT_BYTES,
)
from src.analitica_ml.infrastructure.models import MLModelModel


def test_entrenar_y_recargar_el_modelo_sin_directorio_de_trabajo(saas_world, tmp_path, monkeypatch):
    world = saas_world
    tenant_id = str(world.tenants[1].id)
    trabajo = tmp_path / "trabajo"
    trabajo.mkdir()

    monkeypatch.chdir(trabajo)
    servicio = EntrenamientoService(world.db)
    resultado = servicio.inicializar_datos_y_modelos(tenant_id, seed=7)

    fila = (
        world.db.query(MLModelModel)
        .filter(MLModelModel.id == resultado["demand_model_id"])
        .one()
    )
    assert fila.artifact
    assert fila.artifact_bytes == len(fila.artifact)
    assert fila.artifact_sha256 == GestorArtefactosML.sha256(fila.artifact)
    assert list(trabajo.rglob("*")) == []

    # La inferencia se hace con el artefacto de la base, no con un archivo local.
    monkeypatch.chdir(tmp_path)
    shutil.rmtree(trabajo)

    modelo = servicio.cargar_modelo_activo(tenant_id)
    caracteristicas = np.zeros((2, len(modelo.feature_names)))
    predicciones = servicio.predecir_demanda(tenant_id, caracteristicas)
    assert predicciones.shape == (2,)


def test_artefacto_mayor_a_cinco_megabytes_es_rechazado():
    gestor = GestorArtefactosML()
    with pytest.raises(ArtefactoDemasiadoGrande) as exc:
        gestor.serializar(os.urandom(MAX_ARTIFACT_BYTES + 1024))
    assert exc.value.code == "ml_artifact_too_large"
