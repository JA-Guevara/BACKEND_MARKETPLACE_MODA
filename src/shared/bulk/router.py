import uuid
from hashlib import sha256

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from src.auth.web.dependencies import get_current_user
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import get_permission_codes
from src.shared.bulk.service import process, resource_for, workbook_for
from src.shared.bulk.workbook import MAX_BYTES
from src.shared.exceptions.domain_exception import AuthorizationError, ValidationError
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix='/bulk', tags=['Excel · cargas masivas'])


def authorize(resource, actor, action):
    spec = resource_for(resource)
    if spec.permission + '.' + action not in get_permission_codes(actor):
        raise AuthorizationError('No tiene permisos para esta operación de Excel.')
    return spec


def download(content, filename):
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="{filename}.xlsx"',
                             'Cache-Control': 'no-store'})


@router.get('/{resource}/template')
def template(resource: str, actor: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    spec = authorize(resource, actor, 'read')
    return download(workbook_for(db, spec, template=True), f'plantilla-{resource}')


@router.get('/{resource}/export')
def export(resource: str, search: str = '', include_inactive: bool = True, include_deleted: bool = False,
           branch_id: uuid.UUID | None = None, actor: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    spec = authorize(resource, actor, 'read')
    return download(workbook_for(db, spec, search=search, include_inactive=include_inactive,
                                include_deleted=include_deleted, branch_id=branch_id), f'{resource}-exportacion')


async def read_file(file):
    if not (file.filename or '').lower().endswith('.xlsx'):
        raise ValidationError('Seleccioná un archivo .xlsx.')
    content = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(content) > MAX_BYTES:
        raise ValidationError('Máximo 5 MB por archivo.')
    return content


@router.post('/{resource}/preview')
async def preview(resource: str, file: UploadFile = File(...), mode: str = Form('create'),
                  actor: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    spec = authorize(resource, actor, 'write')
    result = process(db, spec, actor, await read_file(file), mode)
    return ApiResponse(message='Vista previa sin guardar.', data=result)


@router.post('/{resource}/import')
async def import_excel(resource: str, file: UploadFile = File(...), mode: str = Form(...),
                       preview_digest: str = Form(...), confirm: bool = Form(False),
                       actor: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    spec = authorize(resource, actor, 'write')
    content = await read_file(file)
    if not confirm or sha256(content).hexdigest() != preview_digest:
        raise ValidationError('Revisá la vista previa del mismo archivo y confirmá la importación.')
    result = process(db, spec, actor, content, mode, confirm=True)
    return ApiResponse(message='Importación completada.' if result['imported'] else 'No se guardó ningún registro. Corregí las filas indicadas.', data=result)
