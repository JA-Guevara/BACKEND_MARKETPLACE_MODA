from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass
class AuditContext:
    ip_address: str | None
    user_agent: str | None
    request_id: str | None = None
    actor_user_id: UUID | None = None


_context: ContextVar[AuditContext | None] = ContextVar('audit_context', default=None)


def set_audit_context(ip_address: str | None, user_agent: str | None, request_id: str | None = None) -> Token:
    return _context.set(AuditContext(ip_address, user_agent, request_id))


def reset_audit_context(token: Token) -> None:
    _context.reset(token)


def set_audit_actor(user_id: UUID) -> None:
    # The request-owned object is shared with FastAPI worker-thread contexts.
    context = _context.get()
    if context is not None:
        context.actor_user_id = user_id


def get_audit_actor() -> UUID | None:
    context = _context.get()
    return context.actor_user_id if context else None


def get_audit_request_id() -> str | None:
    context = _context.get()
    return context.request_id if context else None


def get_audit_ip_address() -> str | None:
    context = _context.get()
    return context.ip_address if context else None


def get_audit_user_agent() -> str | None:
    context = _context.get()
    return context.user_agent if context else None
