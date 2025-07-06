# app/pipelines/builtins/validate_content_validity.py

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

@register("validate_content_validity")
class ValidateContentValidityStage(LLMStage):
    """
    Etapa de validación que revisa la validez de contenido de un ítem:
    alineación curricular, precisión conceptual y pertinencia pedagógica.
    Actualizado para ser compatible con la nueva arquitectura de payload.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un resultado de validación del LLM."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía el payload completo del ítem, que ahora tiene una estructura anidada,
        para que el validador de contenido tenga todo el contexto necesario.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # Serializa el payload completo a un diccionario.
        # Esto incluye la 'arquitectura' (con el objetivo_aprendizaje),
        # el 'cuerpo_item' y la 'clave_y_diagnostico'.
        item_payload_dict = item.payload.model_dump(mode='json')
        return json.dumps(item_payload_dict, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado de la validación de contenido y actualiza el estado del ítem.
        """
        if not isinstance(result, ValidationResultSchema):
            msg = "Error interno: el esquema de la respuesta del LLM no es ValidationResultSchema."
            self._set_status(item, ItemStatus.FATAL, msg)
            return

        if result.is_valid:
            summary = "Validación de contenido: OK."
            self._set_status(item, ItemStatus.SUCCESS, summary)
        else:
            # El ítem tiene fallos de contenido.
            summary = get_error_message_from_validation_result(result, "Contenido")
            item.findings.extend(result.findings)
            self._set_status(item, ItemStatus.FAIL, summary)
