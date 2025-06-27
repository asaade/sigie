# app/pipelines/builtins/validate_logic.py

from __future__ import annotations
import logging
import json # ¡Importante: necesario para json.dumps!
from typing import List, Type, Dict
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ValidationResultSchema
from app.pipelines.abstractions import LLMStage

logger = logging.getLogger(__name__)

# --- INICIO: Mapeo de severidades desde sigie_error_codes.yaml (ACTUALIZADO CON LA ÚLTIMA VERSIÓN) ---

_ERROR_SEVERITIES: Dict[str, str] = {
    # ERRORES DE ESTILO
    "E020_STEM_LENGTH": "fatal",
    "E040_OPTION_LENGTH": "fatal",
    "E080_MATH_FORMAT": "fatal",
    "W101_STEM_NEG_LOWER": "warning",
    "W104_OPT_LEN_VAR": "warning",
    "W105_LEXICAL_CUE": "warning",
    "W109_PLAUSIBILITY": "warning",
    "W110_REPEATED_KEY": "warning",
    "W112_DISTRACTOR_SIMILAR": "warning",
    "W113_VAGUE_QUANTIFIER": "warning",
    "W123_CONTENIDO_TRIVIAL": "warning",
    "W125_DESCRIPCION_DEFICIENTE": "warning",

    # ERRORES LOGICOS (CON RECLASIFICACIONES DE SEVERIDAD)
    "E070_NO_CORRECT_RATIONALE": "error",
    "E071_CALCULO_INCORRECTO": "error",
    "E072_UNIDADES_INCONSISTENTES": "error",
    "E073_CONTRADICCION_INTERNA": "fatal",
    "E074_NIVEL_COGNITIVO_INAPROPIADO": "fatal",
    "E075_DESCONOCIDO_LOGICO": "fatal",
    "E106_COMPLEX_OPTION_TYPE": "error",

    # ERRORES GENERALES (CON RECLASIFICACIONES DE SEVERIDAD)
    "E001_SCHEMA": "fatal",
    "E010_NUM_OPTIONS": "fatal",
    "E011_DUP_ID": "fatal",
    "E012_CORRECT_COUNT": "fatal",
    "E013_ID_NO_MATCH": "fatal",
    "E030_COMPLET_SEGMENTS": "fatal",
    "E050_BAD_URL": "fatal",
    "E060_MULTI_TESTLET": "fatal",
    "E091_CORRECTA_SIMILAR_STEM": "error",

    # ERRORES DE POLÍTICAS
    "E090_PROFANITY": "fatal",
    "E120_SESGO_GENERO": "error",
    "E121_CULTURAL_EXCL": "error",
    "E122_SESGO_NOMBRE": "error",
    "E124_SESGO_IMAGEN": "error",
    "E126_REFERENCIA_INVALIDA": "error",
    "W102_ABSOL_STEM": "warning",
    "W103_HEDGE_STEM": "warning",
    "W107_COLOR_ALT": "warning",
    "W108_ALT_VAGUE": "warning",

    # ERRORES DE SISTEMA LLM / CALIDAD DE GENERACIÓN
    "E901_LLM_GEN_QUALITY_LOW": "fatal",
    "E902_LLM_CONTEXT_OVERFLOW": "fatal",
    "E903_LLM_SAFETY_VIOLATION": "fatal",
    "E904_NO_LLM_JSON_RESPONSE": "fatal",
    "E905_LLM_CALL_FAILED": "fatal",
    "E906_LLM_PARSE_VALIDATION_ERROR": "fatal",
    "E907_UNEXPECTED_LLM_PROCESSING_ERROR": "fatal",

    # ERRORES DE CONTROL DE FLUJO Y CONFIGURACIÓN DEL PIPELINE
    "E951_PROMPT_NOT_FOUND": "fatal",
    "E952_NO_PAYLOAD": "fatal",
    "E953_ITEM_ID_MISMATCH": "fatal",
    "E954_GEN_INIT_MISMATCH": "fatal",
    "E955_GEN_NO_SUCCESSFUL_OUTPUT": "fatal",
    "E956_LLM_RESPONSE_FORMAT_INVALID": "fatal",
    "E957_LLM_ITEM_COUNT_MISMATCH": "fatal",
    "E958_PIPELINE_CONFIG_ERROR": "fatal",
    "E959_PIPELINE_FATAL_ERROR": "fatal",
}

def get_error_severity(error_code: str) -> str:
    """Consulta la severidad de un código de error desde el mapeo centralizado."""
    # El valor por defecto "error" es una elección segura si un código no se encuentra
    # en el mapeo, asumiendo que cualquier finding del LLM es al menos un "error" corregible.
    return _ERROR_SEVERITIES.get(error_code, "error")

# --- FIN: Mapeo de severidades ---


@register("validate_logic")
class ValidateLogicStage(LLMStage):
    """
    Etapa de validación lógica que utiliza un LLM para identificar errores
    de coherencia, precisión y nivel cognitivo en los ítems.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Define que esperamos un objeto de validación del LLM."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el string de input para el LLM."""
        # Asegurarse de que el payload del ítem exista antes de intentar serializarlo
        if not item.payload:
            self.logger.error(f"Item {item.temp_id} has no payload for _prepare_llm_input in {self.stage_name}.")
            # Se devuelve un JSON de error; la lógica de manejo de errores de LLMStage lo capturará.
            return json.dumps({"error": "No item payload available."})

        # Convertir UUIDs a string para el LLM, para evitar TypeErrors en JSON serialization
        item_dict = item.payload.model_dump(mode='json')
        # Si el item_id es un UUID, convertirlo a string
        if isinstance(item_dict.get("item_id"), (bytes, bytearray)):
             item_dict["item_id"] = str(item.payload.item_id)

        # La respuesta_correcta_id puede ser un Literal en el Pydantic, pero asegurarse de que sea str
        if isinstance(item_dict.get("respuesta_correcta_id"), (bytes, bytearray)):
            item_dict["respuesta_correcta_id"] = str(item.payload.respuesta_correcta_id)

        # Asegurarse de que los IDs de opciones sean string
        for opcion in item_dict.get("opciones", []):
            if isinstance(opcion.get("id"), (bytes, bytearray)):
                opcion["id"] = str(opcion["id"])

        # La entrada para el LLM debe contener el ítem y la metadata de nivel cognitivo
        llm_input_payload = {
            "item_id": str(item.temp_id), # Usar temp_id para el LLM, ya que es el id del objeto Item actual
            "item_payload": item_dict,
            "metadata_context": {
                "nivel_cognitivo": item.payload.metadata.nivel_cognitivo
            }
        }
        return json.dumps(llm_input_payload, indent=2, ensure_ascii=False)


    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa el resultado del LLM: si el ítem es válido o añade hallazgos.
        Aquí es donde re-asignamos la severidad basada en el catálogo YAML.
        """
        has_fatal_finding = False
        processed_findings: List[ReportEntrySchema] = []

        # Iterar sobre los findings del LLM y asignar la severidad real del catálogo
        for llm_finding in result.findings:
            true_severity = get_error_severity(llm_finding.code)
            processed_findings.append(
                ReportEntrySchema(
                    code=llm_finding.code,
                    message=llm_finding.message,
                    field=llm_finding.field,
                    severity=true_severity # ¡Severidad re-asignada!
                )
            )
            if true_severity == "fatal":
                has_fatal_finding = True

        if processed_findings:
            item.findings.extend(processed_findings)
            if has_fatal_finding:
                # Si hay al menos un finding fatal, el outcome global para _set_status es "fatal"
                # _set_status se encargará de poner item.status = "fatal_error"
                self._set_status(item, "fatal", f"Validación lógica: Fallo fatal. {len(processed_findings)} errores críticos encontrados.")
            else:
                # Si no hay findings fatales, pero sí otros errores, el outcome es "fail"
                self._set_status(item, "fail", f"Validación lógica: Falló. {len(processed_findings)} errores encontrados.")
        else:
            # Si el LLM dice que es válido y no hay findings
            self._set_status(item, "success", "Validación lógica: OK.")
