# app/validators/__init__.py

import json
from typing import List, Tuple, Any
from app.pipelines.utils.parsers import extract_json_block
from app.schemas.item_schemas import ReportEntrySchema, LogicValidationResultSchema # Importar el esquema completo

def parse_logic_report(text: str) -> Tuple[LogicValidationResultSchema, List[ReportEntrySchema]]: # Cambio en el primer tipo de retorno
    """
    Parsea la respuesta del Agente Razonamiento (validate_logic).
    Devuelve:
      - parsed_result: Objeto LogicValidationResultSchema.
      - errors: Lista de ReportEntrySchema (errores de parseo si los hay).
    """
    clean_json_str = extract_json_block(text)
    try:
        report_data = LogicValidationResultSchema.model_validate_json(clean_json_str)
        # Los errores del LLM ya están dentro de report_data.errors
        # La utilidad call_llm_and_parse_json_result añadirá los errores de parseo de la utilidad
        return report_data, [] # Devolver lista vacía para errores del parser si la validación Pydantic fue exitosa
    except (json.JSONDecodeError, ValueError) as e:
        return None, [ # Devolver None para el resultado si falla el parseo
            ReportEntrySchema(
                code="LLM_PARSE_ERROR",
                message=f"Fallo al parsear la respuesta del LLM para el reporte lógico: {e}. Raw: {clean_json_str[:200]}...",
                severity="error"
            )
        ]
    except Exception as e:
        return None, [ # Devolver None para el resultado si falla el parseo
            ReportEntrySchema(
                code="UNEXPECTED_PARSE_ERROR",
                message=f"Error inesperado al parsear reporte lógico del LLM: {e}",
                severity="error"
            )
        ]


def parse_policy_report(text: str) -> Tuple[Any, List[ReportEntrySchema]]: # Cambio en el tipo de retorno para custom_parser_func
    """
    Parsea la respuesta del Agente de Políticas (validate_policy).
    Devuelve:
      - policy_report_dict: Un diccionario con 'policy_ok' y 'warnings'/'errors'.
      - errors: Lista de ReportEntrySchema (errores de parseo si los hay).
    """
    clean_json_str = extract_json_block(text)
    try:
        data = json.loads(clean_json_str)
        policy_ok = bool(data.get("policy_ok", False))

        raw_reports = data.get("warnings", []) # El prompt de políticas puede usar "warnings" o "errors"
        # Si el prompt de políticas usa "errors" para errores críticos, ajustar aquí
        if "errors" in data and isinstance(data["errors"], list):
            raw_reports.extend(data["errors"])

        parsed_entries = []
        for entry in raw_reports:
            parsed_entries.append(
                ReportEntrySchema(
                    code=entry.get("warning_code", entry.get("code", "UNKNOWN_CODE")), # Aceptar 'warning_code' o 'code'
                    message=entry.get("message", "Mensaje desconocido."),
                    field=entry.get("field"),
                    severity=entry.get("severity", "warning") # El agente de políticas puede dar warnings o errors
                )
            )
        # Devolvemos un dict con los datos clave del reporte, y los errores/advertencias.
        # Esto es lo que custom_parser_func necesita para pasar la información.
        return {"policy_ok": policy_ok, "reports": parsed_entries}, [] # Devolver lista vacía para errores del parser si el JSON es válido
    except (json.JSONDecodeError, ValueError) as e:
        return None, [ # Devolver None para el resultado si falla el parseo
            ReportEntrySchema(
                code="LLM_PARSE_ERROR_POLICY",
                message=f"Fallo al parsear la respuesta del LLM para el reporte de política: {e}. Raw: {clean_json_str[:200]}...",
                severity="error"
            )
        ]
    except Exception as e:
        return None, [ # Devolver None para el resultado si falla el parseo
            ReportEntrySchema(
                code="UNEXPECTED_PARSE_ERROR_POLICY",
                message=f"Error inesperado al parsear reporte de política del LLM: {e}",
                severity="error"
            )
        ]
