# app/validators/__init__.py

import json
from typing import List, Tuple, Optional

# Es buena práctica manejar el caso de que el parser no se encuentre.
try:
    from app.pipelines.utils.parsers import extract_json_block
except ImportError:
    def extract_json_block(text: str) -> str:
        # Implementación de fallback si el parser no se encuentra
        return text.strip().removeprefix("```json").removesuffix("```").strip()

# --- IMPORT CORREGIDO ---
# Se reemplaza la importación de la obsoleta 'ReportEntrySchema'
# por la nueva y correcta 'FindingSchema'.
from app.schemas.item_schemas import FindingSchema, ValidationResultSchema
from .soft import validate_item_soft

def parse_validation_report(text: str) -> Tuple[Optional[ValidationResultSchema], List[FindingSchema]]:
    """
    Parsea la respuesta de cualquier agente validador (lógica, políticas, etc.).
    Devuelve un objeto ValidationResultSchema y una lista de errores de parseo.
    """
    clean_json_str = extract_json_block(text)
    try:
        report_data = ValidationResultSchema.model_validate_json(clean_json_str)
        return report_data, []
    except (json.JSONDecodeError, ValueError) as e:
        return None, [
            FindingSchema(
                codigo_error="LLM_PARSE_ERROR",
                campo_con_error="llm_response",
                descripcion_hallazgo=f"Fallo al parsear la respuesta del LLM: {e}. Raw: {clean_json_str[:200]}..."
            )
        ]
    except Exception as e:
        return None, [
            FindingSchema(
                codigo_error="UNEXPECTED_PARSE_ERROR",
                campo_con_error="llm_response",
                descripcion_hallazgo=f"Error inesperado al parsear el reporte del LLM: {e}"
            )
        ]

# Puedes definir qué se exporta cuando alguien hace 'from app.validators import *'
__all__ = [
    "validate_item_soft",
    "FindingSchema",
    "ValidationResultSchema",
    "parse_validation_report"
]
