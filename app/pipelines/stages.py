
"""Stage protocol and common helpers for the functional pipeline."""

from __future__ import annotations
from typing import Protocol, List, Dict, Any, runtime_checkable
from app.schemas.models import Item  # reuse existing domain model


@runtime_checkable
class Stage(Protocol):
    """A single asynchronous transformation step.

    Receives a list of ``Item``s plus a shared mutable context ``ctx`` and
    must return a (possibly new) list of ``Item``s.

    Stages should not perform I/O heavy work synchronously; prefer ``await``.
    """

    name: str  # human‑friendly identifier (unique)

    async def __call__(self, items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
        ...
