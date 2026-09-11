import asyncio
from uuid import uuid4

import anyio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import AuditRepository
from src.infrastructure.database.base import Base
from src.main import AuditContextMiddleware
from src.shared.context.audit_context import (
    get_audit_actor, get_audit_ip_address, get_audit_request_id,
    reset_audit_context, set_audit_actor, set_audit_context,
)


def test_actor_is_visible_between_dependency_and_handler_worker_threads():
    async def scenario():
        actor_id = uuid4()
        token = set_audit_context('127.0.0.1', 'test', 'request-1')
        try:
            await anyio.to_thread.run_sync(set_audit_actor, actor_id)
            assert await anyio.to_thread.run_sync(get_audit_actor) == actor_id
        finally:
            reset_audit_context(token)
        assert get_audit_actor() is None
    asyncio.run(scenario())


def test_middleware_ignores_untrusted_forwarded_ip_and_resets_on_error():
    async def scenario():
        async def endpoint(scope, receive, send):
            assert get_audit_ip_address() == '127.0.0.1'
            assert get_audit_request_id()
            raise RuntimeError('endpoint failure')
        scope = {'type': 'http', 'client': ('127.0.0.1', 5000),
                 'headers': [(b'x-forwarded-for', b'8.8.8.8')]}
        try:
            await AuditContextMiddleware(endpoint)(scope, None, None)
        except RuntimeError:
            pass
        assert get_audit_ip_address() is None
        assert get_audit_request_id() is None
    asyncio.run(scenario())


def test_record_falls_back_to_authenticated_actor_and_filters_name_email():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        actor = UserModel(email='ana@fashion.test', first_name='Ana', last_name='Perez', password_hash='unused')
        db.add(actor)
        db.flush()
        token = set_audit_context('127.0.0.1', 'browser', 'request-test')
        try:
            set_audit_actor(actor.id)
            event = RecordAuditEvent(db).execute(action='product.created', entity_type='product', description='Created')
            assert event.actor_user_id == actor.id
            assert event.ip_address == '127.0.0.1'
            assert event.metadata_['request_id'] == 'request-test'
            for term in ('Ana Perez', 'ana@fashion.test'):
                items, total = AuditRepository(db).list(page=1, page_size=30, actor_query=term)
                assert total == 1
                assert items[0].actor_name == 'Ana Perez'
                assert items[0].actor_email == actor.email
            assert AuditRepository(db).list(page=1, page_size=30, actor_query='%')[1] == 0
        finally:
            reset_audit_context(token)
