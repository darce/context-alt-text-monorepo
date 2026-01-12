"""Base handler contracts for worker jobs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class JobHandler[T](ABC):
    """Abstract handler for worker jobs."""

    @abstractmethod
    async def handle(self, job: T, session: AsyncSession) -> None:
        """Process a job and update its status."""
        raise NotImplementedError
