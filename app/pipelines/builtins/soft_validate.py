# app/pipelines/builtins/soft_validate.py
from __future__ import annotations

from typing import List, Dict
from ..registry import register
from app.schemas.models import Item
from app.validators.soft import soft_validate as soft_val


@register("soft_validate")
async def soft_validate_stage(items: List[Item], ctx: Dict[str, any]) -> List[Item]:
    """
    Ejecuta soft_validate y agrega advertencias.
    No invalida el ítem; solo registra warnings.
    """
    reports: list[dict] = []

    for it in items:
        warnings = soft_val(it)           # List[dict] con warning_code y message
        ok = len(warnings) == 0

        msg = "; ".join(w["message"] for w in warnings) or "ok"

        reports.append(
            {
                "item_id": it.item_id,
                "ok": ok,
                "warnings": warnings,    # mantenemos detalle estructurado
                "msg": msg,
            }
        )

    ctx.setdefault("reports", {})["soft_validate"] = reports
    return items  # los ítems no cambian
