"""
app.prompts
Utility to load Markdown prompt templates from disk with caching.

Usage
-----
from app.prompts import load_prompt
tpl = load_prompt("agent_dominio.md")
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Directorio por defecto «…/prompts»
_DEFAULT_DIR = Path(__file__).parents[1] / "prompts"

# Variable de entorno opcional
_ENV_DIR = os.getenv("SIGIE_PROMPTS_DIR")
if _ENV_DIR:
    _DEFAULT_DIR = Path(_ENV_DIR)


@lru_cache(maxsize=32)
def load_prompt(file_name: str) -> str:
    """
    Devuelve el texto del archivo Markdown.

    Parámetros
    ----------
    file_name : str
        Puede ser:
        * Ruta absoluta o relativa a donde se encuentre el proceso,
        * Solo el nombre del archivo ubicado en `${APP_ROOT}/prompts/`.

    Si el nombre no tiene sufijo, se asume «.md».
    Lanza FileNotFoundError si el archivo no existe.
    """
    path = Path(file_name)

    # Si es una ruta relativa, se asume dentro de prompts/
    if not path.is_absolute():
        path = _DEFAULT_DIR / path

    # Añade .md por defecto
    if path.suffix == "":
        path = path.with_suffix(".md")

    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    return path.read_text(encoding="utf-8")
