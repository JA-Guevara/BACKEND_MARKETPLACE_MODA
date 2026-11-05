import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.email_verification_token import EmailVerificationTokenModel
from src.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel


def extract_ip_prefix(ip: str | None) -> str | None:
    if not ip:
        return None
    ip = ip.strip()
    if "." in ip:
        parts = ip.split(".")
        if len(parts) >= 3:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    elif ":" in ip:
        parts = ip.split(":")
        if len(parts) >= 3:
            return f"{parts[0]}:{parts[1]}:{parts[2]}::/48"
    return ip


def extract_device_label(user_agent: str | None) -> str:
    if not user_agent:
        return "Navegador web"
    ua = user_agent.lower()
    os_name = "Dispositivo"
    if "windows" in ua:
        os_name = "Windows"
    elif "macintosh" in ua or "mac os" in ua:
        os_name = "macOS"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "linux" in ua:
        os_name = "Linux"

    browser = "Navegador"
    if "edg" in ua:
        browser = "Edge"
    elif "chrome" in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    elif "dart" in ua or "flutter" in ua:
        browser = "App Móvil"

    return f"{browser} en {os_name}"


class AuthTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add_refresh(self, token: RefreshTokenModel) -> RefreshTokenModel:
        if token.created_by_ip and not token.ip_prefix:
            token.ip_prefix = extract_ip_prefix(token.created_by_ip)
        if token.user_agent and not token.device_label:
            token.device_label = extract_device_label(token.user_agent)
        if not token.last_used_at:
            token.last_used_at = datetime.now(timezone.utc)
        self.db.add(token)
        self.db.flush()
        return token

    def listar_activas(self, user_id: uuid.UUID) -> list[RefreshTokenModel]:
        now = datetime.now(timezone.utc)
        return list(
            self.db.scalars(
                select(RefreshTokenModel)
                .where(
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                    RefreshTokenModel.expires_at > now,
                )
                .order_by(RefreshTokenModel.created_at.desc())
            ).all()
        )

    def revocar(self, id: uuid.UUID, user_id: uuid.UUID, ip_address: str | None = None) -> bool:
        stmt = (
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.id == id,
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc), revoked_by_ip=ip_address)
        )
        res = self.db.execute(stmt)
        return (res.rowcount or 0) > 0

    def revocar_otras(self, user_id: uuid.UUID, actual_jti: str, ip_address: str | None = None) -> int:
        stmt = (
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.jti != actual_jti,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc), revoked_by_ip=ip_address)
        )
        res = self.db.execute(stmt)
        return res.rowcount or 0

    def get_refresh(self, jti: str) -> RefreshTokenModel | None:
        return self.db.scalar(select(RefreshTokenModel).where(RefreshTokenModel.jti == jti))

    def revoke_all_for_user(self, user_id: uuid.UUID, ip_address: str | None = None) -> None:
        self.db.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.user_id == user_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc), revoked_by_ip=ip_address)
        )

    def add_password_reset(self, token: PasswordResetTokenModel) -> None:
        self.db.add(token)
        self.db.flush()

    def get_password_reset(self, token_hash: str) -> PasswordResetTokenModel | None:
        return self.db.scalar(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.token_hash == token_hash)
        )

    def consume_password_resets_for_user(self, user_id: uuid.UUID) -> None:
        self.db.execute(
            update(PasswordResetTokenModel)
            .where(PasswordResetTokenModel.user_id == user_id, PasswordResetTokenModel.used_at.is_(None))
            .values(used_at=datetime.now(timezone.utc))
        )

    def add_email_verification(self, token: EmailVerificationTokenModel) -> None:
        self.db.add(token)
        self.db.flush()

    def get_email_verification(self, token_hash: str) -> EmailVerificationTokenModel | None:
        return self.db.scalar(
            select(EmailVerificationTokenModel).where(EmailVerificationTokenModel.token_hash == token_hash)
        )

    def consume_email_verifications_for_user(self, user_id: uuid.UUID) -> None:
        self.db.execute(
            update(EmailVerificationTokenModel)
            .where(EmailVerificationTokenModel.user_id == user_id, EmailVerificationTokenModel.used_at.is_(None))
            .values(used_at=datetime.now(timezone.utc))
        )
