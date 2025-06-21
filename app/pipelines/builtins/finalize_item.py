# app/pipelines/builtins/finalize_item.py
from __future__ import annotations

from typing import List, Dict

from ..registry import register
from app.schemas.models import Item

# ⚙️ Ajusta este import al helper real que uses para invocar tu LLM
from app.services.llm import call_llm


@register("finalize_item")
async def finalize_item_stage(items: List[Item], ctx: Dict[str, any]) -> List[Item]:
    """
    Ejecuta el Agente Finalizador sobre cada ítem (normalmente 1) y
    registra el reporte final en ctx["reports"]["finalize_item"].
    No modifica el ítem; solo agrega advertencias y un flag final_check_ok.
    """

    reports: list[dict] = []

    modifications_log = ctx.get("modifications", [])

    for it in items:
        # 1️⃣ Construir payload de entrada para el prompt del Agente Finalizador
        payload = {
            "item": it.model_dump() if hasattr(it, "model_dump") else it,  # pydantic o dict
            "modifications": [m for m in modifications_log if m.get("item_id") == it.item_id],
        }

        # 2️⃣ Llamar al LLM con el prompt "agent_final.md"
        llm_response = await call_llm(
            prompt_name="agent_final.md",
            payload=payload,
        )

        # Se espera un objeto JSON con keys: item_id, final_check_ok, final_warnings
        try:
            report = llm_response if isinstance(llm_response, dict) else llm_response.json()
        except Exception as exc:  # noqa: BLE001
            report = {
                "item_id": it.item_id,
                "final_check_ok": False,
                "final_warnings": [
                    {
                        "code": "F_LLM_PARSE_ERROR",
                        "message": f"No se pudo parsear salida LLM: {exc}",
                    }
                ],
            }

        # 3️⃣ Añadir al registro de reports
        reports.append(report)

        # 4️⃣ Opción: marcar flag en Item (si tu modelo lo permite)
        if not report.get("final_check_ok", True):
            it.status = "needs_manual_review"  # type: ignore[attr-defined]

    # Persistimos reporte final
    ctx.setdefault("reports", {})["finalize_item"] = reports
    return items
