# app/prompts/__init__.py
import os
import re
from typing import Dict

PROMPT_DIR = os.path.join(os.path.dirname(__file__))

def load_prompt(name: str) -> Dict[str, str]:
    """
    Carga una plantilla de prompt desde un archivo Markdown y la parsea en
    partes de mensaje del sistema y plantilla de mensaje de usuario.
    Asume que el contenido antes de la primera '---' es el mensaje del sistema.
    El resto del archivo es la plantilla del mensaje de usuario.
    """
    path = os.path.join(PROMPT_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {path}")

    # Dividir el contenido por la primera ocurrencia de '---'
    parts = re.split(r'\n---+\n', content, 1)

    system_message = parts[0].strip() if parts else ""
    user_message_template = parts[1].strip() if len(parts) > 1 else ""

    return {
        "system_message": system_message,
        "user_message_template": user_message_template
    }
