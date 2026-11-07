import csv
from datetime import datetime, timedelta, timezone
import io
from math import ceil
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.dispositivos.infrastructure.models import DeviceModel
from src.dispositivos.web.schemas import DeviceDetailOut, DeviceOut
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.shared.responses.pagination import Page

DEVICE_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class DeviceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _auditar(
        self,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        action: str,
        entity_id: str,
        description: str,
        metadata: dict | None = None,
    ) -> None:
        evt = AuditEventModel(
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=action,
            entity_type="device",
            entity_id=entity_id,
            description=description,
            metadata_=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(evt)

    def verificar_y_registrar(
        self,
        tenant_id: uuid.UUID,
        device_id: str | None,
        platform: str | None = None,
        app_version: str | None = None,
        user_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        op_type: str = "snapshot",
        batch_id: uuid.UUID | None = None,
    ) -> DeviceModel | None:
        if not device_id or not device_id.strip():
            return None

        dev_id = device_id.strip()
        if not DEVICE_ID_REGEX.match(dev_id):
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_device_id", "message": "El formato del device_id no es válido (8-64 caracteres alfanuméricos o guiones)."},
            )

        plat = (platform or "PWA").strip().upper()
        if plat not in ("PWA", "ANDROID"):
            plat = "PWA"

        stmt = select(DeviceModel).where(
            DeviceModel.tenant_id == tenant_id,
            DeviceModel.device_id == dev_id,
        ).with_for_update(of=DeviceModel).execution_options(populate_existing=True)
        device = self.db.scalar(stmt)
        now = datetime.now(timezone.utc)

        if device:
            if device.status == "BLOQUEADO":
                device.rejected_attempts += 1
                device.last_rejected_at = now
                self._auditar(
                    tenant_id=tenant_id,
                    actor_id=user_id,
                    action="devices.blocked_attempt",
                    entity_id=str(device.id),
                    description=f"Intento de acceso rechazado para dispositivo bloqueado ({dev_id}).",
                    metadata={"op_type": op_type, "platform": plat, "app_version": app_version},
                )
                self.db.commit()
                raise HTTPException(
                    status_code=403,
                    detail={"error": "device_blocked", "message": "Dispositivo bloqueado por la empresa"},
                )

            # Actualizar datos de uso
            if app_version:
                device.app_version = app_version
            if user_id:
                device.user_id = user_id
            if branch_id:
                device.branch_id = branch_id

            if op_type == "snapshot":
                device.last_snapshot_at = now
            elif op_type == "sync":
                device.last_sync_at = now
                if batch_id:
                    device.last_batch_id = batch_id
            self.db.flush()
            return device

        # Registro nuevo
        device = DeviceModel(
            tenant_id=tenant_id,
            device_id=dev_id,
            platform=plat,
            app_version=app_version,
            user_id=user_id,
            branch_id=branch_id,
            first_seen_at=now,
            last_snapshot_at=now if op_type == "snapshot" else None,
            last_sync_at=now if op_type == "sync" else None,
            last_batch_id=batch_id if op_type == "sync" else None,
            status="ACTIVO",
            rejected_attempts=0,
        )
        try:
            # Dos primeras peticiones pueden observar que aún no existe. El
            # savepoint conserva la transacción y su contexto al perder el alta.
            with self.db.begin_nested():
                self.db.add(device)
                self.db.flush()
        except IntegrityError:
            concurrent = self.db.scalar(stmt)
            if concurrent is None:
                raise
            # La fila ganadora ya está bloqueada: volver por la validación de
            # estado impide aceptar un dispositivo bloqueado o auditar dos altas.
            return self.verificar_y_registrar(
                tenant_id, dev_id, platform, app_version, user_id, branch_id,
                op_type, batch_id,
            )

        self._auditar(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="devices.registered",
            entity_id=str(device.id),
            description=f"Dispositivo registrado ({plat} {dev_id}).",
            metadata={"op_type": op_type, "platform": plat, "app_version": app_version},
        )
        self.db.flush()
        return device

    def listar(
        self,
        tenant_id: uuid.UUID,
        platform: str | None = None,
        status: str | None = None,
        branch_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        search: str | None = None,
        stale: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[DeviceOut]:
        conditions = [DeviceModel.tenant_id == tenant_id]

        if platform:
            conditions.append(DeviceModel.platform == platform.upper())
        if status:
            conditions.append(DeviceModel.status == status.upper())
        if branch_id:
            conditions.append(DeviceModel.branch_id == branch_id)
        if user_id:
            conditions.append(DeviceModel.user_id == user_id)
        if search and search.strip():
            pat = f"%{search.strip()}%"
            conditions.append(or_(DeviceModel.device_id.ilike(pat), DeviceModel.label.ilike(pat)))
        if stale:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            conditions.append(or_(DeviceModel.last_sync_at == None, DeviceModel.last_sync_at < cutoff))

        count_stmt = select(func.count(DeviceModel.id)).where(*conditions)
        total = self.db.scalar(count_stmt) or 0
        pages = ceil(total / page_size) if total else 0

        stmt = (
            select(DeviceModel)
            .where(*conditions)
            .order_by(DeviceModel.last_sync_at.desc().nullslast(), DeviceModel.first_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        records = list(self.db.scalars(stmt).all())

        items = [
            DeviceOut(
                id=d.id,
                tenant_id=d.tenant_id,
                device_id=d.device_id,
                platform=d.platform,
                label=d.label,
                user_id=d.user_id,
                user_name=f"{d.user.first_name} {d.user.last_name}".strip() if d.user else None,
                branch_id=d.branch_id,
                branch_name=d.branch.name if d.branch else None,
                app_version=d.app_version,
                first_seen_at=d.first_seen_at,
                last_snapshot_at=d.last_snapshot_at,
                last_sync_at=d.last_sync_at,
                last_batch_id=d.last_batch_id,
                status=d.status,
                blocked_at=d.blocked_at,
                block_reason=d.block_reason,
                rejected_attempts=d.rejected_attempts,
                last_rejected_at=d.last_rejected_at,
            )
            for d in records
        ]
        return Page(items=items, total=total, page=page, page_size=page_size, pages=pages)

    def obtener(self, tenant_id: uuid.UUID, device_pk: uuid.UUID) -> DeviceDetailOut:
        stmt = select(DeviceModel).where(
            DeviceModel.tenant_id == tenant_id,
            DeviceModel.id == device_pk,
        )
        d = self.db.scalar(stmt)
        if not d:
            raise NotFoundError("Dispositivo no encontrado.")

        # Obtener últimos 20 eventos de actividad del dispositivo
        events_stmt = (
            select(AuditEventModel)
            .where(
                AuditEventModel.tenant_id == tenant_id,
                AuditEventModel.entity_type == "device",
                AuditEventModel.entity_id == str(d.id),
            )
            .order_by(AuditEventModel.created_at.desc())
            .limit(20)
        )
        raw_events = list(self.db.scalars(events_stmt).all())
        activity = [
            {
                "id": str(e.id),
                "action": e.action,
                "description": e.description,
                "created_at": e.created_at.isoformat(),
                "actor_name": e.actor_name,
                "metadata": e.metadata_,
            }
            for e in raw_events
        ]

        return DeviceDetailOut(
            id=d.id,
            tenant_id=d.tenant_id,
            device_id=d.device_id,
            platform=d.platform,
            label=d.label,
            user_id=d.user_id,
            user_name=f"{d.user.first_name} {d.user.last_name}".strip() if d.user else None,
            branch_id=d.branch_id,
            branch_name=d.branch.name if d.branch else None,
            app_version=d.app_version,
            first_seen_at=d.first_seen_at,
            last_snapshot_at=d.last_snapshot_at,
            last_sync_at=d.last_sync_at,
            last_batch_id=d.last_batch_id,
            status=d.status,
            blocked_at=d.blocked_at,
            block_reason=d.block_reason,
            rejected_attempts=d.rejected_attempts,
            last_rejected_at=d.last_rejected_at,
            recent_activity=activity,
        )

    def bloquear(
        self,
        tenant_id: uuid.UUID,
        device_pk: uuid.UUID,
        actor_id: uuid.UUID | None,
        reason: str,
        revoke_sessions: bool = False,
    ) -> DeviceDetailOut:
        stmt = select(DeviceModel).where(
            DeviceModel.tenant_id == tenant_id,
            DeviceModel.id == device_pk,
        )
        d = self.db.scalar(stmt)
        if not d:
            raise NotFoundError("Dispositivo no encontrado.")
        if d.status == "BLOQUEADO":
            raise ConflictError("El dispositivo ya se encuentra bloqueado.")

        now = datetime.now(timezone.utc)
        d.status = "BLOQUEADO"
        d.blocked_by = actor_id
        d.blocked_at = now
        d.block_reason = reason.strip()

        self._auditar(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="devices.blocked",
            entity_id=str(d.id),
            description=f"Dispositivo bloqueado ({d.device_id}). Motivo: {d.block_reason}",
            metadata={"reason": d.block_reason, "revoke_sessions": revoke_sessions},
        )
        self.db.flush()
        return self.obtener(tenant_id, device_pk)

    def desbloquear(
        self,
        tenant_id: uuid.UUID,
        device_pk: uuid.UUID,
        actor_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> DeviceDetailOut:
        stmt = select(DeviceModel).where(
            DeviceModel.tenant_id == tenant_id,
            DeviceModel.id == device_pk,
        )
        d = self.db.scalar(stmt)
        if not d:
            raise NotFoundError("Dispositivo no encontrado.")

        d.status = "ACTIVO"
        d.blocked_by = None
        d.blocked_at = None
        d.block_reason = None

        self._auditar(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="devices.unblocked",
            entity_id=str(d.id),
            description=f"Dispositivo reactivado ({d.device_id}).",
            metadata={"reason": reason},
        )
        self.db.flush()
        return self.obtener(tenant_id, device_pk)

    def renombrar(
        self,
        tenant_id: uuid.UUID,
        device_pk: uuid.UUID,
        actor_id: uuid.UUID | None,
        label: str,
    ) -> DeviceDetailOut:
        stmt = select(DeviceModel).where(
            DeviceModel.tenant_id == tenant_id,
            DeviceModel.id == device_pk,
        )
        d = self.db.scalar(stmt)
        if not d:
            raise NotFoundError("Dispositivo no encontrado.")

        old_label = d.label
        d.label = label.strip()

        self._auditar(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="devices.renamed",
            entity_id=str(d.id),
            description=f"Dispositivo renombrado de '{old_label}' a '{d.label}'.",
            metadata={"old_label": old_label, "new_label": d.label},
        )
        self.db.flush()
        return self.obtener(tenant_id, device_pk)

    def exportar_csv(self, tenant_id: uuid.UUID) -> str:
        page = self.listar(tenant_id=tenant_id, page=1, page_size=1000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID",
            "Identificador Dispositivo",
            "Etiqueta",
            "Plataforma",
            "Estado",
            "Sucursal",
            "Usuario",
            "Versión App",
            "Primer Registro",
            "Última Sincronización",
            "Última Instantánea",
            "Intentos Rechazados",
            "Motivo de Bloqueo",
        ])
        for it in page.items:
            writer.writerow([
                str(it.id),
                it.device_id,
                it.label or "",
                it.platform,
                it.status,
                it.branch_name or "",
                it.user_name or "",
                it.app_version or "",
                it.first_seen_at.isoformat() if it.first_seen_at else "",
                it.last_sync_at.isoformat() if it.last_sync_at else "",
                it.last_snapshot_at.isoformat() if it.last_snapshot_at else "",
                it.rejected_attempts,
                it.block_reason or "",
            ])
        return output.getvalue()
