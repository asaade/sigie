# app/pipelines/builtins/validate_policy.py

from __future__ import annotations
import json
from typing import Type, Optional
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ValidationResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    get_error_message_from_validation_result,
)

@register("validate_policy")
class ValidatePolicyStage(LLMStage):
    """
    Etapa de validación que revisa si un ítem cumple con las políticas
    de la institución (sesgos, lenguaje inclusivo, accesibilidad, etc.).
    Actualizado para ser compatible con la nueva arquitectura de payload.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un resultado de validación del LLM."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía el payload completo del ítem, ya que el texto de todas las
        partes (enunciado, opciones, justificaciones) es relevante para el
        análisis de políticas.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # Serializa el payload completo a un diccionario para que el LLM
        # tenga acceso a todo el texto del ítem.
        item_payload_dict = item.payload.model_dump(mode='json')
        return json.dumps(item_payload_dict, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado de la validación de políticas y actualiza el estado del ítem.
        """
        if not isinstance(result, ValidationResultSchema):
            msg = "Error interno: el esquema de la respuesta del LLM no es ValidationResultSchema."
            self._set_status(item, ItemStatus.FATAL, msg)
            return

        if result.is_valid:
            summary = "Validación de políticas: OK."
            self._set_status(item, ItemStatus.SUCCESS, summary)
        else:
            # El ítem tiene violaciones de políticas.
            summary = get_error_message_from_validation_result(result, "Políticas")
            item.findings.extend(result.findings)
            self._set_status(item, ItemStatus.FAIL, summary)
