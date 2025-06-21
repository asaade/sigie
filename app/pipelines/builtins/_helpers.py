
"""Common helpers for LLM stages."""
from typing import Dict

def add_tokens(ctx: Dict, tokens: int):
    ctx['usage_tokens_total'] = ctx.get('usage_tokens_total', 0) + tokens
