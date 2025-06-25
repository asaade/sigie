# Archivo actualizado: app/validators/__init__.py

import json
from typing import List, Tuple
from app.pipelines.utils.parsers import extract_json_block
from app.schemas.item_schemas import ReportEntrySchema, ValidationResultSchema

def parse_validation_report(text: str) -> Tuple[ValidationResultSchema, List[ReportEntrySchema]]:
    """
    Parsea la respuesta de CUALQUIER agente validador (lógica, políticas, etc.).
    Devuelve:
      - parsed_result: Objeto ValidationResultSchema.
      - errors: Lista de ReportEntrySchema (solo si hay errores de parseo).
    """
    clean_json_str = extract_json_block(text)
    try:
        # Usamos el esquema genérico para validar el JSON.
        # Este esquema espera las claves "is_valid" y "findings".
        report_data = ValidationResultSchema.model_validate_json(clean_json_str)
        # Si la validación Pydantic es exitosa, no hay errores de parseo que reportar.
        return report_data, []
    except (json.JSONDecodeError, ValueError) as e:
        # Si el JSON está mal formado o no se puede parsear.
        return None, [
            ReportEntrySchema(
                code="LLM_PARSE_ERROR",
                message=f"Fallo al parsear la respuesta del LLM: {e}. Raw: {clean_json_str[:200]}...",
                severity="error"
            )
        ]
    except Exception as e:
        # Cualquier otro error inesperado durante el parseo.
        return None, [
            ReportEntrySchema(
                code="UNEXPECTED_PARSE_ERROR",
                message=f"Error inesperado al parsear el reporte del LLM: {e}",
                severity="error"
            )
        ]

# Nota: Las funciones originales 'parse_logic_report' y 'parse_policy_report'
# ahora pueden ser reemplazadas por esta única función genérica 'parse_validation_report'.
# Deberás asegurar que las etapas que usaban un 'custom_parser_func' ahora
# simplemente pasen 'expected_schema=ValidationResultSchema' a la utilidad 'call_llm_and_parse_json_result',
# que ya maneja este parseo internamente sin necesidad de un parser customizado.
# O, si prefieres mantener los parsers custom, asegúrate de que usen esta nueva lógica.
