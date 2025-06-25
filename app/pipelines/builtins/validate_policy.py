# app/pipelines/builtins/validate_policy.py

from __future__ import annotations
from typing import Type
from pydantic import BaseModel

import logging
from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ValidationResultSchema # Usamos ValidationResultSchema
# ELIMINADO: from app.validators import parse_policy_report # Ya no se importa directamente

from app.pipelines.abstractions import LLMStage # Importamos LLMStage


logger = logging.getLogger(__name__)

@register("validate_policy")
class ValidatePolicyStage(LLMStage): # Convertido a clase que hereda de LLMStage
    """
    Etapa de validación de políticas de ítems mediante un LLM (Agente de Políticas).
    Ahora implementada como una clase Stage, utilizando el esquema de validación unificado.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Define que esperamos un objeto ValidationResultSchema del LLM para esta etapa.
        """
        return ValidationResultSchema # CRÍTICO: Usamos ValidationResultSchema directamente

    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el string de input para el LLM, enviando el payload completo del ítem."""
        return item.payload.model_dump_json(indent=2)

    async def _process_llm_result(self, item: Item, result: ValidationResultSchema): # Result ahora es ValidationResultSchema
        """
        Procesa el resultado de la validación de políticas.
        Los hallazgos (errores y advertencias) se añaden a la lista unificada 'findings'.
        """
        if result.is_valid:
            self._set_status(item, "success", "Policy validation passed.")
        else:
            # Los hallazgos del LLM ya están en result.findings
            item.findings.extend(result.findings) # Extiende a la lista unificada item.findings
            summary = f"Policy validation failed. {len(result.findings)} issues found."
            self._set_status(item, "fail", summary) # Usar _set_status de BaseStage
            self.logger.warning(f"Item {item.temp_id} failed policy validation. Findings: {result.findings}")

    # ELIMINADO: _get_custom_parser_func. Ahora la utilidad LLM hará el parseo directo.
