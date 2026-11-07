from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.repositories.auth_token_repository import AuthTokenRepository
from src.auth.infrastructure.security.jwt_service import JWTService
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.http.schemas import (
    AuthUserResponse,
    AuthorizedBranchSummary,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TenantSummary,
    TokenResponse,
    VerifyEmailRequest,
    UserSessionResponse,
    RevokeOthersRequest,
)
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.database.session import get_db
from src.infrastructure.http.maintenance import maintenance_response
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.infrastructure.security.tenancy import get_public_tenant_id
from src.inventario_sucursales.application.services.user_branch_service import UserBranchService
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    UserBranchModel,
)
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.support import SupportSessionResponse
from src.shared.exceptions.domain_exception import AuthenticationError, MaintenanceError
from src.shared.responses.api_response import ApiResponse


router = APIRouter(prefix="/auth", tags=['PAQ-01 · Usuarios y catálogo'])


def request_context(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _authorized_branches(db: Session, ctx: AccessContext) -> list[AuthorizedBranchSummary]:
    if ctx.tenant_id is None:
        return []
    if ctx.is_support:
        branches = list(
            db.scalars(
                select(BranchModel)
                .where(
                    BranchModel.tenant_id == ctx.tenant_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
                .order_by(BranchModel.code)
            ).all()
        )
    else:
        branches = UserBranchService(db, ctx.tenant_id, ctx.user.id).autorizadas(ctx.user)

    defaults = set(
        db.scalars(
            select(UserBranchModel.branch_id).where(
                UserBranchModel.tenant_id == ctx.tenant_id,
                UserBranchModel.user_id == ctx.user.id,
                UserBranchModel.is_default.is_(True),
            )
        ).all()
    )
    if not defaults and branches:
        defaults = {branches[0].id}
    return [
        AuthorizedBranchSummary(
            id=branch.id,
            code=branch.code,
            name=branch.name,
            is_default=branch.id in defaults,
        )
        for branch in branches
    ]


@router.post("/register", response_model=ApiResponse[AuthUserResponse], status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, tenant_id: UUID = Depends(get_public_tenant_id), db: Session = Depends(get_db)):
    ip, user_agent = request_context(request)
    user = AuthService(db, tenant_id).register(data, ip_address=ip, user_agent=user_agent)
    return ApiResponse(message="Cuenta registrada. Revise su correo para verificarla.", data=user)


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip, user_agent = request_context(request)
    platform_only = getattr(request.state, "maintenance_platform_only", False)
    try:
        tokens = AuthService(db).login(
            str(data.email),
            data.password,
            ip_address=ip,
            user_agent=user_agent,
            platform_only=platform_only,
            tenant_slug=data.tenant_slug,
            platform_login=data.platform_login,
        )
    except (MaintenanceError, AuthenticationError):
        if not platform_only:
            raise
        # La misma respuesta para cuentas de empresa, desconocidas y fallos
        # de autenticación de plataforma evita revelar qué correo es operador.
        return maintenance_response()
    return ApiResponse(message="Inicio de sesion exitoso.", data=tokens)


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
def refresh(data: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    ip, _ = request_context(request)
    tokens = AuthService(db).refresh(data.refresh_token, ip_address=ip)
    return ApiResponse(message="Sesion renovada.", data=tokens)


@router.post("/logout", response_model=ApiResponse[None])
def logout(data: LogoutRequest, request: Request, db: Session = Depends(get_db)):
    ip, _ = request_context(request)
    AuthService(db).logout(data.refresh_token, ip_address=ip)
    return ApiResponse(message="Sesion cerrada.")


@router.get("/me", response_model=ApiResponse[AuthUserResponse])
def me(ctx: AccessContext = Depends(get_access_context), db: Session = Depends(get_db)):
    user = ctx.user
    response = AuthUserResponse.model_validate(user)
    response.read_only = ctx.read_only
    response.must_change_password = bool(getattr(user, "must_change_password", False))
    if ctx.is_support:
        tenant = SaasRepository(db).get_tenant(ctx.tenant_id)
        if tenant:
            response.tenant = TenantSummary.model_validate(tenant)
        response.subscription = PlanGuard(db).resumen(ctx.tenant_id)
        session = db.get(SupportSessionModel, ctx.support_session_id)
        if session:
            now = datetime.now(timezone.utc)
            tenant_name = (tenant.trade_name or tenant.legal_name) if tenant else "Empresa"
            actions_count = db.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.support_session_id == session.id
                )
            ) or 0
            response.support = SupportSessionResponse(
                id=session.id,
                tenant_id=session.tenant_id,
                tenant_name=tenant_name,
                platform_user_id=session.platform_user_id,
                platform_user_name=f"{user.first_name} {user.last_name}".strip(),
                reason=session.reason,
                duration_minutes=session.duration_minutes,
                started_at=session.started_at,
                expires_at=session.expires_at,
                ended_at=session.ended_at,
                end_reason=session.end_reason,
                actions_count=actions_count,
                is_active=session.is_active(now),
            )
        db.commit()
    elif user.tenant_id:
        response.tenant = TenantSummary.model_validate(SaasRepository(db).get_tenant(user.tenant_id))
        is_client = bool(user.roles) and all(getattr(r, "code", "") == "client" for r in user.roles)
        if not is_client:
            response.subscription = PlanGuard(db).resumen(user.tenant_id)
        else:
            response.subscription = None
        db.commit()
    response.authorized_branches = _authorized_branches(db, ctx)
    return ApiResponse(message="Usuario autenticado.", data=response)


@router.post("/forgot-password", response_model=ApiResponse[None])
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    AuthService(db).request_password_reset(str(data.email))
    return ApiResponse(message="Si el correo existe, recibira instrucciones para recuperar su contrasena.")


@router.post("/reset-password", response_model=ApiResponse[None])
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    AuthService(db).reset_password(data.token, data.new_password)
    return ApiResponse(message="Contrasena restablecida.")


@router.post("/change-password", response_model=ApiResponse[None])
def change_password(
    data: ChangePasswordRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AuthService(db).change_password(user, data.current_password, data.new_password)
    return ApiResponse(message="Contrasena modificada. Inicie sesion nuevamente.")


@router.post("/verify-email", response_model=ApiResponse[None])
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    AuthService(db).verify_email(data.token)
    return ApiResponse(message="Correo electronico verificado.")


@router.post("/resend-verification", response_model=ApiResponse[None])
def resend_verification(data: ResendVerificationRequest, db: Session = Depends(get_db)):
    AuthService(db).resend_verification(str(data.email))
    return ApiResponse(message="Si corresponde, se envio un nuevo enlace de verificacion.")

@router.get("/sessions", response_model=ApiResponse[list[UserSessionResponse]])
def list_sessions(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    repo = AuthTokenRepository(db)
    active_tokens = repo.listar_activas(user.id)
    data = [UserSessionResponse.model_validate(t) for t in active_tokens]
    return ApiResponse(message="Sesiones activas listadas.", data=data)


@router.delete("/sessions/{id}", response_model=ApiResponse[None])
def revoke_session(
    id: UUID,
    request: Request,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip, _ = request_context(request)
    repo = AuthTokenRepository(db)
    revoked = repo.revocar(id, user.id, ip_address=ip)
    db.commit()
    return ApiResponse(message="Sesion revocada." if revoked else "Sesion no encontrada o ya revocada.")


@router.post("/sessions/revoke-others", response_model=ApiResponse[dict[str, int]])
def revoke_other_sessions(
    request: Request,
    data: RevokeOthersRequest | None = None,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip, _ = request_context(request)
    repo = AuthTokenRepository(db)
    current_jti = None
    if data:
        if data.current_jti:
            current_jti = data.current_jti
        elif data.refresh_token or data.current_refresh_token:
            raw = data.refresh_token or data.current_refresh_token
            try:
                payload = JWTService().decode(raw, "refresh")
                current_jti = payload.get("jti")
            except Exception:
                pass
        elif data.session_id or data.current_session_id:
            sid = data.session_id or data.current_session_id
            token_model = db.get(RefreshTokenModel, sid)
            if token_model and token_model.user_id == user.id:
                current_jti = token_model.jti

    if not current_jti:
        active = repo.listar_activas(user.id)
        if active:
            current_jti = active[0].jti
        else:
            current_jti = ""

    revoked_count = repo.revocar_otras(user.id, current_jti, ip_address=ip)
    db.commit()
    return ApiResponse(message="Otras sesiones revocadas.", data={"revoked_count": revoked_count})

