
from string import Template

def fill_template(text: str, params: dict[str, str]) -> str:
    """Replace placeholders like {area} with params values."""
    for key, val in params.items():
        text = text.replace(f"{{{key}}}", str(val))
    return text
