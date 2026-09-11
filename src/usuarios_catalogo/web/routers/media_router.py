from pathlib import Path
from typing import Annotated
import re

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.shared.responses.api_response import ApiResponse
from src.usuarios_catalogo.infrastructure.media_storage import store_image

router = APIRouter(prefix='/media', tags=['Product images'])

@router.post('/images', status_code=201)
async def upload_image(request: Request, actor: Annotated[UserModel, Depends(require_permissions('catalog.write'))], file: UploadFile = File(...), db: Session = Depends(get_db)):
    limit = settings.media_max_upload_mb * 1024 * 1024
    try:
        raw = await file.read(limit + 1)
    finally:
        await file.close()
    if not raw or len(raw) > limit:
        raise ValidationError(f'La imagen debe pesar entre 1 byte y {settings.media_max_upload_mb} MB.')
    directory = Path(settings.media_storage_dir).resolve()
    name, width, height = store_image(raw, directory)
    public_base = settings.media_public_base_url.rstrip('/')
    url = f'{public_base}/{name}' if public_base else str(request.url_for('media_file', name=name))
    RecordAuditEvent(db).execute(actor_user_id=actor.id, action='catalog.image_uploaded', entity_type='product_image', entity_id=name, description='Imagen validada y cargada.', metadata={'width':width,'height':height,'bytes':len(raw)})
    db.commit()
    return ApiResponse(message='Imagen cargada.', data={'url':url,'name':name,'width':width,'height':height})

@router.get('/files/{name}', name='media_file')
def media_file(name: str):
    if not re.fullmatch(r'[0-9a-f]{32}\.webp', name):
        raise NotFoundError('Imagen no encontrada.')
    path = Path(settings.media_storage_dir).resolve() / name
    if not path.is_file():
        raise NotFoundError('Imagen no encontrada.')
    return FileResponse(path, media_type='image/webp', headers={'X-Content-Type-Options':'nosniff','Cache-Control':'public, max-age=31536000, immutable'})
