# app/validators/__init__.py

import json
from app.pipelines.utils.parsers import extract_json_block

def parse_logic_report(text: str) -> tuple[bool, str]:
    """
    Parsea la respuesta del Agente Razonamiento (validate_logic).
    Extrae el bloque JSON, lo convierte en dict, y devuelve:
      - logic_ok: bool del campo "logic_ok"
      - msg: concatenación de todos los errores (campo "errors")
    """
    clean = extract_json_block(text)
    data = json.loads(clean)
    logic_ok = bool(data.get("logic_ok", False))
    # Cada error es {code: ..., message: ...}
    errors = data.get("errors", [])
    msg = "; ".join(err.get("message", "") for err in errors)
    return logic_ok, msg

def parse_policy_report(text: str) -> tuple[bool, str]:
    """
    Parsea la respuesta del Agente de Políticas (validate_policy).
    Extrae el bloque JSON, lo convierte en dict, y devuelve:
      - policy_ok: bool del campo "policy_ok"
      - msg: concatenación de todos los errores (campo "errors")
    """
    clean = extract_json_block(text)
    data = json.loads(clean)
    policy_ok = bool(data.get("policy_ok", False))
    errors = data.get("errors", [])
    msg = "; ".join(err.get("message", "") for err in errors)
    return policy_ok, msg
