from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.http.schemas import (
    AuthUserResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.shared.responses.api_response import ApiResponse


router = APIRouter(prefix="/auth", tags=["authentication"])


def request_context(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


@router.post("/register", response_model=ApiResponse[AuthUserResponse], status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip, user_agent = request_context(request)
    user = AuthService(db).register(data, ip_address=ip, user_agent=user_agent)
    return ApiResponse(message="Cuenta registrada. Revise su correo para verificarla.", data=user)


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip, user_agent = request_context(request)
    tokens = AuthService(db).login(str(data.email), data.password, ip_address=ip, user_agent=user_agent)
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
def me(user: UserModel = Depends(get_current_user)):
    return ApiResponse(message="Usuario autenticado.", data=user)


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
