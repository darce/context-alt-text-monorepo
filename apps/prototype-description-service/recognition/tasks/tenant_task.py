"""Tenant-aware task helpers for async workers and scripts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context

T = TypeVar("T")


def tenant_task(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    Decorator that supplies an AsyncSession with tenant context to the wrapped task.

    Usage:

        @tenant_task
        async def recompute(session: AsyncSession, *, threshold: float):
            ...

        await recompute(tenant_id=some_uuid, threshold=0.6)
    """

    @wraps(func)
    async def wrapper(*, tenant_id: UUID, **kwargs: Any) -> T:
        async with async_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            try:
                return await func(session, **kwargs)
            finally:
                await clear_tenant_context(session)

    return wrapper
