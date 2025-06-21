# app/validators/__init__.py

import json
from typing import List, Tuple
from app.pipelines.utils.parsers import extract_json_block
from app.schemas.item_schemas import ReportEntrySchema, LogicValidationResultSchema # Importar el esquema completo

def parse_logic_report(text: str) -> Tuple[bool, List[ReportEntrySchema]]:
    """
    Parsea la respuesta del Agente Razonamiento (validate_logic).
    Extrae el bloque JSON, lo convierte en el esquema LogicValidationResultSchema,
    y devuelve:
      - logic_ok: bool del campo "logic_ok"
      - errors: Lista de ReportEntrySchema (añadiendo severity="error" si no está presente)
    """
    clean_json_str = extract_json_block(text)
    try:
        # Validar la respuesta del LLM directamente con el esquema Pydantic
        report_data = LogicValidationResultSchema.model_validate_json(clean_json_str)

        # Asegurar que cada error tenga severity="error" como este agente sólo reporta errores críticos
        processed_errors = []
        for error in report_data.errors:
            processed_errors.append(
                ReportEntrySchema(
                    code=error.code,
                    message=error.message,
                    field=error.field,
                    severity="error" # Forzar severity a "error" para este agente
                )
            )

        return report_data.logic_ok, processed_errors
    except (json.JSONDecodeError, ValueError) as e:
        # Si el JSON es inválido o no se ajusta al esquema
        return False, [
            ReportEntrySchema(
                code="LLM_PARSE_ERROR",
                message=f"Fallo al parsear la respuesta del LLM para el reporte lógico: {e}. Raw: {clean_json_str[:200]}...",
                severity="error"
            )
        ]
    except Exception as e:
        # Cualquier otro error inesperado
        return False, [
            ReportEntrySchema(
                code="UNEXPECTED_PARSE_ERROR",
                message=f"Error inesperado al parsear reporte lógico del LLM: {e}",
                severity="error"
            )
        ]


def parse_policy_report(text: str) -> Tuple[bool, List[ReportEntrySchema]]:
    """
    Parsea la respuesta del Agente de Políticas (validate_policy).
    Extrae el bloque JSON, lo convierte en dict, y devuelve:
      - policy_ok: bool del campo "policy_ok"
      - warnings: Lista de ReportEntrySchema (este agente emite warnings)
    """
    clean_json_str = extract_json_block(text)
    try:
        data = json.loads(clean_json_str)
        policy_ok = bool(data.get("policy_ok", False))

        raw_errors_warnings = data.get("warnings", []) # El prompt de políticas usa "warnings"
        parsed_entries = []
        for entry in raw_errors_warnings:
            # Asumir que el LLM puede dar severity, o forzar a 'warning' si es el agente de políticas
            parsed_entries.append(
                ReportEntrySchema(
                    code=entry.get("warning_code", "UNKNOWN_CODE"), # Prompt usa warning_code
                    message=entry.get("message", "Mensaje desconocido."),
                    field=entry.get("field"), # Si el LLM lo proporciona
                    severity=entry.get("severity", "warning") # El agente de políticas sí puede dar warnings
                )
            )
        return policy_ok, parsed_entries
    except (json.JSONDecodeError, ValueError) as e:
        return False, [
            ReportEntrySchema(
                code="LLM_PARSE_ERROR_POLICY",
                message=f"Fallo al parsear la respuesta del LLM para el reporte de política: {e}. Raw: {clean_json_str[:200]}...",
                severity="error" # Un error de parseo es fatal aquí
            )
        ]
    except Exception as e:
        return False, [
            ReportEntrySchema(
                code="UNEXPECTED_PARSE_ERROR_POLICY",
                message=f"Error inesperado al parsear reporte de política del LLM: {e}",
                severity="error"
            )
        ]
