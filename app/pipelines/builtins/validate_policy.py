# Archivo actualizado: app/pipelines/builtins/validate_policy.py

from __future__ import annotations
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ValidationResultSchema
from app.pipelines.abstractions import LLMStage

@register("validate_policy")
class ValidatePolicyStage(LLMStage):
    """
    Etapa de validación de políticas institucionales y de estilo.
    Utiliza el esqueleto de LLMStage para verificar que el ítem cumpla
    con las directrices definidas.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Utiliza el esquema de validación genérico, esperando un veredicto
        y una lista de hallazgos.
        """
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM enviando el payload completo del ítem
        para su revisión.
        """
        return item.payload.model_dump_json(indent=2)

    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa el resultado de la validación de políticas. Los hallazgos se
        registran como advertencias (warnings).
        """
        if result.is_valid:
            # El ítem cumple con las políticas.
            self._set_status(item, "success", "Policy validation passed.")
        else:
            # El ítem no cumple. Los hallazgos son advertencias.
            item.warnings.extend(result.findings)
            summary = f"Policy validation failed. {len(result.findings)} warnings issued."
            self._set_status(item, "fail", summary)
