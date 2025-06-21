from __future__ import annotations
from typing import List, Dict
from ..registry import register
from app.llm import generate_response
from app.prompts import load_prompt
from app.schemas.models import Item
from app.validators import parse_policy_report
from ..utils.parsers import extract_json_block

@register("validate_policy")
async def validate_policy_stage(items: List[Item], ctx: Dict[str, any]) -> List[Item]:
    params = ctx["params"]["validate_policy"]
    prompt_template = load_prompt(params["prompt"])

    reports: list[Dict] = []
    total_tokens = 0

    for it in items:
        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user",   "content": it.to_json()},
        ]
        resp = await generate_response(messages)
        total_tokens += getattr(resp, "usage", {}).get("total", 0)

        clean = extract_json_block(resp.text)
        ok, msg = parse_policy_report(clean)

        if not ok:
            it.status = "invalid_policy"
        reports.append({"item_id": it.item_id or it.temp_id, "ok": ok, "msg": msg})

    ctx["reports"]["validate_policy"] = reports
    from ._helpers import add_tokens
    add_tokens(ctx, total_tokens)

    return items
