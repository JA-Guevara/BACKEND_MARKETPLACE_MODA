import asyncio
import logging
from contextlib import suppress
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import SessionLocal
from src.plataforma_saas.application.tenant_backup_service import process_backups


async def backup_loop():
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(process_backups,SessionLocal)
        except Exception:
            logging.getLogger(__name__).error('tenant_backup_worker_failed')


def start_worker():
    if settings.app_env=='test' or not settings.tenant_backup_worker_enabled:
        return None
    return asyncio.create_task(backup_loop())


async def stop_worker(task):
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
