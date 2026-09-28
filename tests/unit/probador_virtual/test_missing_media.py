import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.infrastructure.config.settings import settings
from src.probador_virtual.domain.exceptions import SinRecursoARError
from src.probador_virtual.infrastructure.services.virtual_fitting_service import VirtualFittingService


def test_recurso_preparado_sin_archivo_no_se_anuncia_como_listo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path))
    nombre = "a" * 32 + ".webp"
    producto_id, color_id = uuid.uuid4(), uuid.uuid4()
    producto = SimpleNamespace(id=producto_id, is_active=True, deleted_at=None)
    recurso = SimpleNamespace(
        usable=True, color_id=color_id, mode="2.5d",
        transparent_url=f"https://api.example.org/api/v1/media/files/{nombre}",
        mask_url=None, model_3d_url=None, garment_type="shirt",
        body_region="upper_body", anchor_points=None,
    )
    db = MagicMock()
    db.get.return_value = producto
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = [recurso]
    servicio = VirtualFittingService(db)

    with pytest.raises(SinRecursoARError, match="ya no está disponible"):
        servicio.resolve_asset(producto_id, color_id)

    (tmp_path / nombre).write_bytes(b"imagen")
    experiencia = servicio.resolve_asset(producto_id, color_id)
    assert experiencia.asset_url.endswith(nombre)
