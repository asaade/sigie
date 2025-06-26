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
    system_template: str,
    user_message_template: str, # Esta es la plantilla completa del prompt después de ---
    payload: Union[Dict[str, Any], List[Any], str], # Esta es la carga útil JSON real
) -> List[Dict[str, str]]:
    """
    Construye una lista de mensajes system+user para la API del LLM.
    Enfáticamente separa las instrucciones de los parámetros de entrada.
    """
    if isinstance(payload, str):
        user_content_payload_str = payload
    else:
        # Asegurarse de que el payload JSON se formatee bien para el prompt
        user_content_payload_str = json.dumps(payload, ensure_ascii=False, indent=2)

    # MODIFICADO: Claramente separar las instrucciones del prompt de los parámetros de entrada.
    # Esto ayuda al LLM a diferenciar entre las instrucciones de su tarea y los datos de entrada.
    final_user_message_content = (
        f"{user_message_template}\n\n"
        f"--- INICIO DE PARÁMETROS DE ENTRADA ---\n"
        f"```json\n{user_content_payload_str}\n```\n"
        f"--- FIN DE PARÁMETROS DE ENTRADA ---\n\n"
        f"Recuerda: Tu respuesta debe ser *solo* el arreglo JSON de ítems, conforme a la 'Estructura de Salida Esperada'."
    )

    messages = []
    if system_template:
        messages.append({"role": "system", "content": system_template})
    messages.append({"role": "user", "content": final_user_message_content})

    return messages
