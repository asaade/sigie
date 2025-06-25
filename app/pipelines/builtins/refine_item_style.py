# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import logging # Necesario para logging.info/debug/warning
import json

from typing import Type # Necesario para List[Item] y Type[BaseModel]
from pydantic import BaseModel # Necesario para Type[BaseModel]

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema

from app.pipelines.abstractions import LLMStage # CRÍTICO: Importamos LLMStage

# Mantenemos solo las helpers que NO son métodos de LLMStage/BaseStage
# y que se usan directamente en el código específico de la etapa.
from ..utils.stage_helpers import (
    clean_specific_errors, # Esta helper es específica para limpiar códigos, y no es un método de BaseStage/LLMStage
    handle_item_id_mismatch_refinement, # Esta helper se mantiene si no la movemos a un método de LLMStage
)


logger = logging.getLogger(__name__) # Definir logger para este módulo

@register("refine_item_style")
class RefineStyleStage(LLMStage): # CRÍTICO: Convertido a clase que hereda de LLMStage
    """
    Etapa de refinamiento de estilo que corrige un ítem en un solo paso.
    Implementada como una clase Stage.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Define el esquema Pydantic para la respuesta del LLM (RefinementResultSchema)."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM. Envía el payload completo del ítem
        junto con una lista vacía de problemas para una revisión integral de estilo.
        """
        # Se envía un array de 'problems' vacío para mantener una estructura
        # de input consistente con el refinador lógico si el prompt lo requiere.
        input_payload = {
            "item": item.payload.model_dump(),
            "problems": []
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema):
        """
        Procesa el resultado del LLM: reemplaza el payload del ítem por la
        versión con el estilo corregido y limpia los hallazgos.
        """
        # Verificación de seguridad: asegurar que el LLM corrigió el ítem correcto.
        if result.item_id != item.payload.item_id:
            # Usamos el helper de stage_helpers
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in style correction response."
            )
            return

        # Aplica la corrección: reemplaza el payload del ítem
        item.payload = result.item_refinado

        # Limpia los hallazgos (errores/advertencias) que el LLM reporta haber corregido.
        # Esto asume que el refinador de estilo limpia las advertencias de estilo previas.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes) # Usamos el helper de stage_helpers

        # Marcar el estado de éxito y registrar la auditoría.
        summary = f"Style correction applied. {len(result.correcciones_realizadas)} corrections reported."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
