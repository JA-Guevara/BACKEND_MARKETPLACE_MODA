from datetime import datetime, timedelta, timezone
from math import ceil
import os
from pathlib import Path
import re

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.operacion_offline.infrastructure.models.sync import SyncBatchModel
from src.plataforma_saas.infrastructure.models.ops import PlatformBackup
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.shared.exceptions.base_exception import AppException
from src.shared.exceptions.domain_exception import ConflictError


class BackupDispatchError(AppException):
    status_code = 502
    code = "backup_dispatch_failed"


class OpsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def registrar_respaldo(self, data: dict) -> PlatformBackup:
        if data["sha256"] is None:
            conditions = (
                PlatformBackup.sha256.is_(None), PlatformBackup.workflow_run_url == data["workflow_run_url"],
            )
        else:
            conditions = (PlatformBackup.sha256 == data["sha256"],)
        query = select(PlatformBackup).where(*conditions).with_for_update()
        existing = self.db.scalar(query)
        if existing is None:
            try:
                with self.db.begin_nested():
                    existing = PlatformBackup(**data)
                    self.db.add(existing)
                    self.db.flush()
            except IntegrityError:
                # Un reporte simultáneo puede insertar el mismo SHA primero.
                existing = self.db.scalar(query)
                if existing is None:
                    raise
            else:
                self.db.commit()
                return existing

        status = data["verify_status"]
        if (existing.verify_status == "pending" and status != "pending") or (
            existing.verify_status == "failed" and status == "ok"
        ):
            if any(getattr(existing, key) != data[key] for key in ("size_bytes", "alembic_revision", "pg_server_version")):
                raise ConflictError("Los metadatos de la copia no coinciden con el reporte anterior.")
            # Conserva la fecha original del dump para evitar rejuvenecer una copia al verificarla otra vez.
            existing.verify_status = status
            existing.verify_report = data["verify_report"]
            self.db.commit()
        return existing

    def listar_respaldos(self, page: int, page_size: int) -> dict:
        total = self.db.scalar(select(func.count()).select_from(PlatformBackup)) or 0
        items = self.db.scalars(select(PlatformBackup).order_by(
            PlatformBackup.finished_at.desc(), PlatformBackup.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)).all()
        return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": ceil(total / page_size)}

    def ultimo_verificado(self, revision: str | None = None) -> PlatformBackup | None:
        query = select(PlatformBackup).where(PlatformBackup.verify_status == "ok")
        if revision is not None:
            query = query.where(PlatformBackup.alembic_revision == revision)
        return self.db.scalar(query.order_by(PlatformBackup.finished_at.desc(), PlatformBackup.id.desc()).limit(1))

    def estado(self, *, version: str | None = None, rate_limited: int | None = None) -> dict:
        now = datetime.now(timezone.utc)
        revisions = MigrationContext.configure(self.db.connection()).get_current_heads()
        migration_dir = Path(__file__).resolve().parents[3] / "alembic"
        head = ScriptDirectory(str(migration_dir)).get_current_head()
        ultimo = self.ultimo_verificado()
        backup = None
        if ultimo is not None:
            finished = ultimo.finished_at
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            backup = {
                "id": ultimo.id,
                "finished_at": finished,
                "age_hours": max(0, (now - finished).total_seconds() / 3600),
                "alembic_revision": ultimo.alembic_revision,
            }

        equipo = (
            UserModel.tenant_id.is_(None), UserModel.is_active.is_(True), UserModel.deleted_at.is_(None),
            UserModel.roles.any((RoleModel.audience == "PLATFORM") & RoleModel.is_active.is_(True)
                                & RoleModel.tenant_id.is_(None)),
        )
        mfa_enabled_at = getattr(UserModel, "mfa_enabled_at", None)
        mfa_enrolled = None if mfa_enabled_at is None else self.db.scalar(
            select(func.count()).select_from(UserModel).where(*equipo, mfa_enabled_at.is_not(None))
        )
        return {
            "version": version,
            "git_sha": os.getenv("RAILWAY_GIT_COMMIT_SHA"),
            "app_env": settings.app_env,
            "revision_bd": revisions[0] if len(revisions) == 1 else None,
            "cabeza_codigo": head,
            "migraciones_pendientes": revisions != (head,),
            "ultimo_respaldo": backup,
            "mantenimiento": settings.maintenance_mode,
            "contadores": {
                "rate_limited": rate_limited,
                "sync_rechazadas_24h": self.db.scalar(select(func.coalesce(func.sum(SyncBatchModel.rejected), 0)).where(
                    SyncBatchModel.finished_at > now - timedelta(hours=24),
                )),
                "cuentas_bloqueadas": self.db.scalar(select(func.count()).select_from(UserModel).where(
                    UserModel.locked_until > now, UserModel.deleted_at.is_(None),
                )),
                "mfa_adopcion": {
                    "total": self.db.scalar(select(func.count()).select_from(UserModel).where(*equipo)),
                    "habilitadas": mfa_enrolled,
                },
            },
        }

    def despachar_respaldo(self, actor: UserModel, reason: str) -> dict:
        repo = settings.github_repo or ""
        secret = settings.github_dispatch_token
        token = secret.get_secret_value() if secret is not None else ""
        if not token or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", repo) or repo.split("/")[-1] in {".", ".."}:
            raise ConflictError(
                "Configura GITHUB_DISPATCH_TOKEN y GITHUB_REPO para solicitar un respaldo.",
                code="dispatch_not_configured",
            )
        try:
            response = httpx.post(
                f"https://api.github.com/repos/{repo}/actions/workflows/respaldo-bd.yml/dispatches",
                json={"ref": "main", "inputs": {"tipo": "manual"}},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise BackupDispatchError("GitHub no pudo aceptar la solicitud de respaldo.") from None

        RecordAuditEvent(self.db).execute(
            action="platform.backup_requested",
            entity_type="platform_backup",
            actor_user_id=actor.id,
            description="Se solicitó una copia manual desde la consola de operación.",
            metadata={"reason": reason},
        )
        self.db.commit()
        return {"dispatched": True}
