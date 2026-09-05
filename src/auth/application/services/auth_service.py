from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.auth.application.services.auth_email_service import AuthEmailService
from src.auth.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    InactiveAccountError,
    InvalidCredentialsError,
)
from src.auth.domain.password_policy import PasswordPolicy
from src.auth.infrastructure.http.schemas import RegisterRequest, TokenResponse
from src.auth.infrastructure.persistence.models.email_verification_token import EmailVerificationTokenModel
from src.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.repositories.auth_token_repository import AuthTokenRepository
from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.roles.infrastructure.persistence.repositories.role_repository import RoleRepository
from src.shared.exceptions.domain_exception import AuthenticationError, ConflictError


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.tokens = AuthTokenRepository(db)
        self.roles = RoleRepository(db)
        self.audit = RecordAuditEvent(db)
        self.passwords = PasswordHasher()
        self.jwt = JWTService()
        self.email = AuthEmailService()

    def register(self, data: RegisterRequest, *, ip_address: str | None, user_agent: str | None) -> UserModel:
        PasswordPolicy.validate(data.password, email=str(data.email))
        if self.users.get_by_email(str(data.email), include_deleted=True):
            raise EmailAlreadyExistsError()
        client_role = self.roles.get_role_by_code("client")
        if not client_role:
            raise ConflictError("El rol base de cliente no existe. Revise la migracion inicial.")
        user = UserModel(
            email=str(data.email).lower(),
            password_hash=self.passwords.hash(data.password),
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            phone=data.phone,
            roles=[client_role],
        )
        self.users.add(user)
        raw_token, token_hash = self.jwt.create_opaque_token()
        self.tokens.add_email_verification(
            EmailVerificationTokenModel(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.verification_token_expire_hours),
            )
        )
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.register",
            entity_type="user",
            entity_id=str(user.id),
            description="Cuenta de cliente registrada.",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        self.email.send_verification(user.email, raw_token)
        return self.users.get_by_id(user.id) or user

    def login(self, email: str, password: str, *, ip_address: str | None, user_agent: str | None) -> TokenResponse:
        user = self.users.get_by_email(email)
        now = datetime.now(timezone.utc)
        if not user:
            self.audit.execute(
                action="auth.login_failed",
                entity_type="user",
                description="Intento de inicio de sesion con correo inexistente.",
                metadata={"email": email.lower()},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveAccountError("La cuenta esta desactivada.")
        if user.locked_until and user.locked_until > now:
            raise AccountLockedError(f"La cuenta esta bloqueada hasta {user.locked_until.isoformat()}.")
        if not self.passwords.verify(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_login_attempts:
                user.locked_until = now + timedelta(minutes=settings.account_lock_minutes)
                user.failed_login_attempts = 0
            self.audit.execute(
                actor_user_id=user.id,
                action="auth.login_failed",
                entity_type="user",
                entity_id=str(user.id),
                description="Contrasena incorrecta.",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise InvalidCredentialsError()
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        response = self._issue_tokens(user, ip_address)
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.login",
            entity_type="user",
            entity_id=str(user.id),
            description="Inicio de sesion exitoso.",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        return response

    def refresh(self, raw_token: str, *, ip_address: str | None) -> TokenResponse:
        payload = self.jwt.decode(raw_token, "refresh")
        stored = self.tokens.get_refresh(payload["jti"])
        if not stored or stored.token_hash != self.jwt.hash_token(raw_token):
            raise AuthenticationError("Token de renovacion invalido.")
        if stored.revoked_at:
            self.tokens.revoke_all_for_user(stored.user_id, ip_address)
            self.db.commit()
            raise AuthenticationError("Se detecto reutilizacion de un token revocado.")
        now = datetime.now(timezone.utc)
        if stored.expires_at <= now:
            raise AuthenticationError("Token de renovacion expirado.")
        user = self.users.get_by_id(stored.user_id)
        if not user or not user.is_active:
            raise AuthenticationError("La cuenta no esta disponible.")
        response = self._issue_tokens(user, ip_address)
        replacement_payload = self.jwt.decode(response.refresh_token, "refresh")
        stored.revoked_at = now
        stored.revoked_by_ip = ip_address
        stored.replaced_by_jti = replacement_payload["jti"]
        self.db.commit()
        return response

    def logout(self, raw_token: str, *, ip_address: str | None) -> None:
        payload = self.jwt.decode(raw_token, "refresh")
        stored = self.tokens.get_refresh(payload["jti"])
        if stored and not stored.revoked_at and stored.token_hash == self.jwt.hash_token(raw_token):
            stored.revoked_at = datetime.now(timezone.utc)
            stored.revoked_by_ip = ip_address
            self.audit.execute(
                actor_user_id=stored.user_id,
                action="auth.logout",
                entity_type="user",
                entity_id=str(stored.user_id),
                description="Sesion cerrada.",
                ip_address=ip_address,
            )
            self.db.commit()

    def request_password_reset(self, email: str) -> None:
        user = self.users.get_by_email(email)
        if not user or not user.is_active:
            return
        raw_token, token_hash = self.jwt.create_opaque_token()
        self.tokens.add_password_reset(
            PasswordResetTokenModel(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.password_reset_token_expire_minutes),
            )
        )
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.password_reset_requested",
            entity_type="user",
            entity_id=str(user.id),
            description="Recuperacion de contrasena solicitada.",
        )
        self.db.commit()
        self.email.send_password_reset(user.email, raw_token)

    def reset_password(self, raw_token: str, new_password: str) -> None:
        stored = self.tokens.get_password_reset(self.jwt.hash_token(raw_token))
        now = datetime.now(timezone.utc)
        if not stored or stored.used_at or stored.expires_at <= now:
            raise AuthenticationError("El enlace de recuperacion es invalido o expiro.")
        user = self.users.get_by_id(stored.user_id)
        if not user or not user.is_active:
            raise AuthenticationError("La cuenta no esta disponible.")
        PasswordPolicy.validate(new_password, email=user.email)
        if self.passwords.verify(new_password, user.password_hash):
            raise ConflictError("La nueva contrasena debe ser diferente de la actual.")
        user.password_hash = self.passwords.hash(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        self.tokens.consume_password_resets_for_user(user.id)
        self.tokens.revoke_all_for_user(user.id)
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.password_reset",
            entity_type="user",
            entity_id=str(user.id),
            description="Contrasena restablecida.",
        )
        self.db.commit()

    def change_password(self, user: UserModel, current_password: str, new_password: str) -> None:
        if not self.passwords.verify(current_password, user.password_hash):
            raise InvalidCredentialsError()
        PasswordPolicy.validate(new_password, email=user.email)
        if self.passwords.verify(new_password, user.password_hash):
            raise ConflictError("La nueva contrasena debe ser diferente de la actual.")
        user.password_hash = self.passwords.hash(new_password)
        self.tokens.revoke_all_for_user(user.id)
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.password_changed",
            entity_type="user",
            entity_id=str(user.id),
            description="Contrasena modificada.",
        )
        self.db.commit()

    def verify_email(self, raw_token: str) -> None:
        stored = self.tokens.get_email_verification(self.jwt.hash_token(raw_token))
        now = datetime.now(timezone.utc)
        if not stored or stored.used_at or stored.expires_at <= now:
            raise AuthenticationError("El enlace de verificacion es invalido o expiro.")
        user = self.users.get_by_id(stored.user_id)
        if not user:
            raise AuthenticationError("La cuenta no esta disponible.")
        user.is_verified = True
        self.tokens.consume_email_verifications_for_user(user.id)
        self.audit.execute(
            actor_user_id=user.id,
            action="auth.email_verified",
            entity_type="user",
            entity_id=str(user.id),
            description="Correo electronico verificado.",
        )
        self.db.commit()

    def resend_verification(self, email: str) -> None:
        user = self.users.get_by_email(email)
        if not user or not user.is_active or user.is_verified:
            return
        raw_token, token_hash = self.jwt.create_opaque_token()
        self.tokens.add_email_verification(
            EmailVerificationTokenModel(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.verification_token_expire_hours),
            )
        )
        self.db.commit()
        self.email.send_verification(user.email, raw_token)

    def _issue_tokens(self, user: UserModel, ip_address: str | None) -> TokenResponse:
        access_token, expires_in = self.jwt.create_access_token(str(user.id))
        refresh_token, jti, expires_at = self.jwt.create_refresh_token(str(user.id))
        self.tokens.add_refresh(
            RefreshTokenModel(
                user_id=user.id,
                jti=jti,
                token_hash=self.jwt.hash_token(refresh_token),
                expires_at=expires_at,
                created_by_ip=ip_address,
            )
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=user,
        )
