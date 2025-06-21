
from __future__ import annotations
from typing import List, Dict
from ..registry import register
from app.schemas.models import Item
from app.db.session import SessionLocal
# from sqlalchemy.orm import Session

@register("persist")
async def persist_stage(items: List[Item], ctx: Dict[str, any]) -> List[Item]:
    orm_items = [it.to_orm() for it in items]

    with SessionLocal() as db:  # type: Session
        db.bulk_save_objects(orm_items)
        db.commit()

    ctx["db_inserted"] = len(orm_items)
    return items
