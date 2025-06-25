# app/prompts/__init__.py

from pathlib import Path
from app.core.config import get_settings

settings = get_settings()

# Asumimos que la configuración tiene una variable para el directorio de prompts.
# Si no, se puede definir aquí o en `constants.py`.
PROMPTS_DIR = Path(settings.PROMPTS_DIR) if hasattr(settings, 'PROMPTS_DIR') else Path(__file__).parent

def load_prompt(name: str) -> str:
    """
    Carga un prompt desde el directorio de prompts.
    Lanza FileNotFoundError si no existe.
    """
    path = PROMPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found at path: {path}")
    return path.read_text(encoding="utf-8")
