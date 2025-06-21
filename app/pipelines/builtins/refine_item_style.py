# app/pipelines/builtins/refine_item_style.py
from __future__ import annotations
from typing import List, Dict

from ..registry import register
from .refine_item import refine_item_stage   # Reutilizamos la lógica existente

@register("refine_item_style")
async def refine_item_style_stage(items: List, ctx: Dict[str, any]):
    """
    Wrapper que inyecta el prompt del refinador de estilo
    y delega en refine_item_stage.
    """
    ctx.setdefault("params", {}).setdefault("refine_item", {})
    ctx["params"]["refine_item"]["prompt"] = "agente_refinador_estilo.md"
    ctx["params"]["refine_item"]["tag"] = "style"
    return await refine_item_stage(items, ctx)
