# app/pipelines/builtins/validate_style.py
from __future__ import annotations

import json
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.llm import generate_response
from app.prompts import load_prompt
from ..utils.parsers import extract_json_block

@register("validate_style")
async def validate_style_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    • Envía cada ítem al LLM con el prompt de validación de estilo.
    • Espera un objeto JSON: {item_id, style_ok, warnings:[{code,message}]}.
    • NO modifica el ítem; solo registra el reporte.
    """
    params = ctx["params"]["validate_style"]
    prompt_tpl = load_prompt(params["prompt"])

    reports: list[dict] = []
    total_tokens = 0

    for it in items:
        # 1️⃣ Construir mensajes
        messages = [
            {"role": "system", "content": prompt_tpl},
            {"role": "user",   "content": it.model_dump_json()},
        ]

        resp = await generate_response(messages, temperature=params.get("temperature"))
        total_tokens += getattr(resp, "usage", {}).get("total", 0)

        # 2️⃣ Intentar extraer el bloque JSON
        clean_json = extract_json_block(resp.text)
        try:
            report = json.loads(clean_json)
            # Estructura mínima esperada
            assert "item_id" in report and "style_ok" in report
            reports.append(report)
        except Exception as exc:  # noqa: BLE001
            # Fallback: registrar fallo de parseo
            reports.append({
                "item_id": it.item_id,
                "style_ok": False,
                "warnings": [
                    {"code": "W_STYLE_PARSE", "message": f"Error al interpretar salida LLM: {exc}"}
                ],
            })

    # 3️⃣ Guardar reporte y tokens
    ctx.setdefault("reports", {})["validate_style"] = reports
    from ._helpers import add_tokens
    add_tokens(ctx, total_tokens)

    # 4️⃣ Devolvemos los ítems sin cambios
    return items
