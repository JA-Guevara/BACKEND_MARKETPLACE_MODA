from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.tenant_backup_service import TenantBackupService, public_run, process_backups
from src.shared.exceptions.domain_exception import AuthorizationError
from src.shared.responses.api_response import ApiResponse

router=APIRouter(tags=['PAQ-06 · Datos y respaldos de empresa'])
TenantActor=Annotated[UserModel,Depends(require_permissions('tenant.data_export'))]
PlatformReader=Annotated[UserModel,Depends(require_platform_permissions('platform.ops.read'))]
PlatformWriter=Annotated[UserModel,Depends(require_platform_permissions('platform.ops.write'))]


class PolicyIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool
    frequency: Literal['daily','weekly']='daily'
    hour: int=Field(3,ge=0,le=23)
    timezone: str=Field('America/La_Paz',max_length=80)
    retention: int=Field(7,ge=1,le=14)
    @field_validator('timezone')
    @classmethod
    def known_timezone(cls,value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Zona horaria no válida.') from None
        return value


class CreateIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID


def owned(ctx,actor,db):
    if ctx.support_session_id or actor.tenant_id!=ctx.tenant_id:
        raise AuthorizationError('Las copias de empresa requieren una cuenta propia; las sesiones de soporte no permiten descargarlas.')
    return TenantBackupService(db,ctx.tenant_id,actor)


def file_response(service,run_id):
    return Response(service.download(run_id),media_type='application/zip',headers={
        'Content-Disposition':f'attachment; filename="fashionstore-empresa-{run_id}.zip"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/tenant/backups',response_model=ApiResponse[dict])
def listing(ctx:TenantScope,actor:TenantActor,page:int=Query(1,ge=1),db:Session=Depends(get_db)):
    return ApiResponse(data=owned(ctx,actor,db).status(page))


@router.put('/tenant/backups/policy',response_model=ApiResponse[dict])
def policy(data:PolicyIn,ctx:TenantScope,actor:TenantActor,db:Session=Depends(get_db)):
    return ApiResponse(data=owned(ctx,actor,db).configure(data.model_dump()))


@router.post('/tenant/backups',response_model=ApiResponse[dict],status_code=202)
def create(data:CreateIn,ctx:TenantScope,actor:TenantActor,db:Session=Depends(get_db)):
    return ApiResponse(data=public_run(owned(ctx,actor,db).enqueue(str(data.request_id))))


@router.get('/tenant/backups/{run_id}/download')
def download(run_id:UUID,ctx:TenantScope,actor:TenantActor,db:Session=Depends(get_db)):
    return file_response(owned(ctx,actor,db),run_id)


@router.get('/platform/backups/tenants', response_model=ApiResponse[dict])
def platform_all_tenants_backups(
    actor: PlatformReader,
    search: str | None = Query(None),
    policy_filter: Literal['all', 'enabled', 'disabled'] = Query('all'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Módulo de administración global para Super Admin: vista y estado de respaldos por empresa."""
    return ApiResponse(
        data=TenantBackupService.all_tenants_overview(
            db,
            actor=actor,
            search=search,
            policy_filter=policy_filter,
            page=page,
            page_size=page_size,
        )
    )


@router.post('/platform/backups/process-queue', response_model=ApiResponse[dict])
def platform_process_queue(actor: PlatformWriter, db: Session = Depends(get_db)):
    """Procesamiento inmediato de la cola de respaldos de empresas."""
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    processed = process_backups(factory, limit=10)
    return ApiResponse(data={'processed': processed, 'message': f'Se procesaron {processed} copias en cola.'})


@router.get('/platform/tenants/{tenant_id}/backups',response_model=ApiResponse[dict])
def platform_listing(tenant_id:UUID,actor:PlatformReader,page:int=Query(1,ge=1),db:Session=Depends(get_db)):
    return ApiResponse(data=TenantBackupService(db,tenant_id,actor).status(page))


@router.put('/platform/tenants/{tenant_id}/backups/policy',response_model=ApiResponse[dict])
def platform_policy(tenant_id:UUID,data:PolicyIn,actor:PlatformWriter,db:Session=Depends(get_db)):
    return ApiResponse(data=TenantBackupService(db,tenant_id,actor).configure(data.model_dump()))


@router.post('/platform/tenants/{tenant_id}/backups',response_model=ApiResponse[dict],status_code=202)
def platform_create(tenant_id:UUID,data:CreateIn,actor:PlatformWriter,db:Session=Depends(get_db)):
    return ApiResponse(data=public_run(TenantBackupService(db,tenant_id,actor).enqueue(str(data.request_id))))


@router.get('/platform/tenants/{tenant_id}/backups/{run_id}/download')
def platform_download(tenant_id:UUID,run_id:UUID,actor:PlatformWriter,db:Session=Depends(get_db)):
    return file_response(TenantBackupService(db,tenant_id,actor),run_id)
