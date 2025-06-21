# app/pipelines/builtins/refine_item_logic.py
from __future__ import annotations
from typing import List, Dict

from ..registry import register
from .refine_item import refine_item_stage

@register("refine_item_logic")
async def refine_item_logic_stage(items: List, ctx: Dict[str, any]):
    ctx.setdefault("params", {}).setdefault("refine_item", {})
    ctx["params"]["refine_item"]["prompt"] = "agente_refinador_logico.md"
    ctx["params"]["refine_item"]["tag"] = "logic"
    return await refine_item_stage(items, ctx)
