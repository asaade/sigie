# app/pipelines/utils/parsers.py

"""
Utilities to extract JSON from LLM responses and build prompt messages.
"""

import json
import re
from typing import Any, Dict, List, Union

# Detecta bloques ```json ... ```
_JSON_FENCE = re.compile(r"```json\s*([\s\S]*?)```", re.IGNORECASE)

def extract_json_block(text: str) -> str:
    """
    Si hay un bloque marcado con ```json … ```, devuelve solo su contenido.
    En caso contrario, devuelve el texto entero.
    """
    m = _JSON_FENCE.search(text)
    return m.group(1).strip() if m else text

def parse_payload(text: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Limpia fences y parsea JSON. Retorna dict o lista.
    """
    clean = extract_json_block(text)
    return json.loads(clean)

def build_prompt_messages(
    template: str,
    payload: Union[Dict[str, Any], List[Any], str],
) -> List[Dict[str, str]]:
    """
    Construye un par de mensajes system+user:
      - system: la plantilla.
      - user: el JSON serializado de `payload`.
    Si `payload` ya es str, lo usa tal cual (no lo vuelve a dump).
    """
    if isinstance(payload, str):
        user_content = payload
    else:
        user_content = json.dumps(payload, ensure_ascii=False)
    return [
        {"role": "system", "content": template},
        {"role": "user", "content": user_content},
    ]
