from __future__ import annotations
from typing import List, Dict
from deepdiff import DeepDiff
from pydantic import ValidationError
from app.schemas.models import Item
from app.llm import generate_response
from app.prompts import load_prompt
from app.schemas.item_schemas import ItemPayloadSchema
from ..registry import register
from ..utils.parsers import extract_json_block

@register("refine_item")
async def refine_item_stage(items: List[Item], ctx: Dict[str, any]) -> List[Item]:
    params = ctx.get("params", {}).get("refine_item", {})
    prompt_template = load_prompt(params.get("prompt", ""))
    tag = params.get("tag", "refine_item")

    new_items: List[Item] = []
    reports: List[Dict] = []
    total_tokens = 0

    for it in items:
        # Guardar estado original para diff
        original_data = it.model_dump() if hasattr(it, "model_dump") else it

        # Construir mensajes para LLM
        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": it.payload.model_dump_json()},
        ]

        # Llamada al LLM
        resp = await generate_response(messages)
        total_tokens += getattr(resp, "usage", {}).get("total", 0)

        # Obtener texto de la respuesta
        response_text = getattr(resp, "text", None)
        if response_text is None and hasattr(resp, "choices"):
            try:
                response_text = resp.choices[0].message.content
            except Exception:
                response_text = str(resp)

        # Extraer bloque JSON y validarlo
        clean = extract_json_block(response_text)
        try:
            payload = ItemPayloadSchema.model_validate_json(clean)
            new_it = Item.from_payload(payload)
            new_items.append(new_it)

            # Calcular diferencias y registrar modificaciones
            diff = DeepDiff(original_data, new_it.model_dump(), ignore_order=True, report_repetition=True)
            for change_type, changes in diff.items():
                if change_type != "values_changed":
                    continue
                for path, change in changes.items():
                    field = path.replace("root", "").replace("['", ".").replace("']", "").lstrip('.')
                    ctx.setdefault("modifications", []).append({
                        "item_id": it.item_id or getattr(it, "temp_id", None),
                        "agent": tag,
                        "field": field,
                        "code": tag.upper(),
                        "original": change.get("old_value"),
                        "corrected": change.get("new_value"),
                    })

            reports.append({"item_id": it.item_id or getattr(it, "temp_id", None), "ok": True, "msg": ""})
        except ValidationError as ve:
            # Si falla validación, conservar ítem original y marcar fallo
            it.status = "refine_failed"
            new_items.append(it)
            reports.append({"item_id": it.item_id or getattr(it, "temp_id", None), "ok": False, "msg": str(ve)})

    # Registrar reportes y tokens
    ctx.setdefault("reports", {})["refine_item"] = reports
    from ._helpers import add_tokens
    add_tokens(ctx, total_tokens)

    return new_items
