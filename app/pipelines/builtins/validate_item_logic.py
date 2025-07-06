# app/pipelines/builtins/validate_item_logic.py

from __future__ import annotations
import json
from typing import Type, Optional
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus # Ensure ItemStatus is imported
from app.schemas.item_schemas import ValidationResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    get_error_message_from_validation_result,
)

@register("validate_item_logic")
class ValidateItemLogicStage(LLMStage):
    """
    Etapa de validación que revisa la consistencia lógica interna de un ítem.
    Actualizado para ser compatible con la nueva arquitectura de payload.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un resultado de validación del LLM."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía el payload completo del ítem, que ahora tiene una estructura anidada.
        """
        if not item.payload:
            # Esta comprobación es importante por si un ítem llega sin payload.
            # En este caso, el LLM recibirá un payload vacío con un mensaje de error.
            # La etapa base ya maneja el estado FATAL si el payload falta al inicio.
            return json.dumps({"error": "Item payload is missing."})

        # item.payload es un objeto Pydantic. model_dump() lo serializa a un dict
        # que puede ser convertido a JSON, respetando la nueva estructura.
        item_payload_dict = item.payload.model_dump(mode='json')
        return json.dumps(item_payload_dict, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado de la validación lógica y actualiza el estado del ítem.
        """
        if result is None:
            self.logger.info(f"Item {item.temp_id} en {self.stage_name}: No se recibió resultado del LLM.")
            return

        if not isinstance(result, ValidationResultSchema):
            msg = f"Error interno: el esquema de la respuesta del LLM no es ValidationResultSchema, es {type(result).__name__}."
            self._set_status(item, ItemStatus.FATAL, msg)
            return

        if result.is_valid:
            summary = "Validación lógica: OK."
            self._set_status(item, ItemStatus.SUCCESS, summary)
        else:
            summary = get_error_message_from_validation_result(result, "Lógica")
            item.findings.extend(result.findings)
            self._set_status(item, ItemStatus.FAIL, summary)
