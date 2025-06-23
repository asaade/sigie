# app/pipelines/builtins/validate_policy.py

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
        """Utiliza el esquema de validación genérico."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el input para el LLM enviando el payload del ítem."""
        return item.payload.model_dump_json(indent=2)

    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa el resultado de la validación de políticas. Los hallazgos se
        añaden a la lista unificada 'findings'.
        """
        if result.is_valid:
            # El ítem cumple con las políticas.
            self._set_status(item, "success", "Policy validation passed.")
        else:
            # El ítem no cumple. Los hallazgos se guardan en la lista unificada.
            # El prompt se encargará de que cada hallazgo tenga la 'severity' correcta.
            # ▼▼▼ CAMBIO PRINCIPAL AQUÍ ▼▼▼
            item.findings.extend(result.findings)
            summary = f"Policy validation failed. {len(result.findings)} issues found."
            self._set_status(item, "fail", summary)
