import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.email_verification_token import EmailVerificationTokenModel
from src.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel


class AuthTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add_refresh(self, token: RefreshTokenModel) -> RefreshTokenModel:
        self.db.add(token)
        self.db.flush()
        return token

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
