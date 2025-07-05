# app/prompts/__init__.py

import logging
from pathlib import Path
from typing import Dict, Union

logger = logging.getLogger(__name__)

PROMPT_SEPARATOR = "***"

_PROMPT_CACHE: Dict[str, Union[str, Dict[str, str]]] = {}
_PROMPTS_DIR = Path(__file__).parent.resolve()

def load_prompt(prompt_name: str) -> Union[str, Dict[str, str]]:
    """
    Carga un prompt desde el archivo .md correspondiente, lo cachea y lo devuelve.
    Ahora utiliza '***' como el separador para dividir el system_message del content.
    """
    if prompt_name in _PROMPT_CACHE:
        return _PROMPT_CACHE[prompt_name]

    try:
        file_path = _PROMPTS_DIR / prompt_name
        with open(file_path, 'r', encoding='utf-8') as f:
            full_content = f.read()

        # Se busca el separador '***'
        if PROMPT_SEPARATOR in full_content:
            parts = full_content.split(PROMPT_SEPARATOR, 1)
            system_message = parts[0].strip()
            content_template = parts[1].strip()

            prompt_data = {
                "system_message": system_message,
                "content": content_template
            }
            _PROMPT_CACHE[prompt_name] = prompt_data
            return prompt_data
        else:
            # Si no hay separador, se trata todo como una sola plantilla.
            _PROMPT_CACHE[prompt_name] = full_content
            return full_content

    except FileNotFoundError:
        logger.error(f"Error: Archivo de prompt no encontrado en '{file_path}'")
        raise
    except Exception as e:
        logger.error(f"Error al cargar el prompt '{prompt_name}': {e}")
        raise
