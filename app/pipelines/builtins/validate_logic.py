# Archivo actualizado: app/pipelines/builtins/validate_logic.py

from __future__ import annotations
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
# Importamos los esquemas estandarizados que definimos
from app.schemas.item_schemas import ValidationResultSchema
# Importamos la clase base de nuestra nueva abstracción
from app.pipelines.abstractions import LLMStage

@register("validate_logic")
class ValidateLogicStage(LLMStage):
    """
    Etapa de validación lógica que utiliza el esqueleto de LLMStage.
    Su única responsabilidad es implementar la lógica de negocio específica
    para la validación de la coherencia lógica de un ítem.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Define el formato de respuesta que esperamos del LLM para esta etapa.
        Usamos el esquema de validación genérico.
        """
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM. Para una validación, simplemente
        enviamos el payload completo del ítem como un string JSON.
        """
        return item.payload.model_dump_json(indent=2)

    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa un resultado exitoso del LLM.
        Esta es la lógica de negocio central de la etapa.
        """
        if result.is_valid:
            # El ítem pasó la validación. Usamos el helper de la clase base
            # para actualizar el estado a 'validate_logic.success' y auditar.
            self._set_status(item, "success", "Logic validation passed.")
        else:
            # El ítem falló la validación. Añadimos los hallazgos a los errores
            # del ítem y usamos el helper para actualizar el estado a 'validate_logic.fail'.
            # La política indica que los fallos de lógica son errores.
            item.errors.extend(result.findings)
            summary = f"Logic validation failed. {len(result.findings)} issues found."
            self._set_status(item, "fail", summary)
