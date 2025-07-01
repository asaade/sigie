# app/pipelines/builtins/refine_item_logic.py

from __future__ import annotations
import logging
import json # Necesario para json.dumps en _prepare_llm_input
import asyncio # Necesario para asyncio.gather

from typing import Type, Optional, List, Any, Dict # Asegurar que List, Any, Dict estén importados
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema, ReportEntrySchema # Importar ReportEntrySchema

from app.pipelines.abstractions import LLMStage # Importar LLMStage para heredar

from ..utils.stage_helpers import (
    clean_specific_errors,
    handle_item_id_mismatch_refinement,
    # skip_if_terminal_error ya está en LLMStage si se necesita, pero no en execute de BaseStage.
    # handle_missing_payload también suele estar en LLMStage o BaseStage, o se puede llamar desde aquí.
)


logger = logging.getLogger(__name__)

@register("refine_item_logic")
class RefineLogicStage(LLMStage): # Hereda de LLMStage
    def _get_expected_schema(self) -> Type[BaseModel]:
        """Devuelve el esquema Pydantic para la respuesta del LLM (RefinementResultSchema)."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Incluye el payload del ítem y la lista de hallazgos lógicos a corregir.
        """
        # Filtrar solo los hallazgos de severidad 'error' para esta etapa de refinamiento lógico.
        # Esto incluye errores de validate_logic o cualquier error acumulado que sea lógico.
        # Aunque el prompt se refiere a 'hallazgos lógicos', el filtro es por severidad 'error'.
        relevant_problems_to_fix: List[ReportEntrySchema] = [
            f for f in item.findings if f.severity == 'error'
        ]

        if not item.payload:
            self.logger.error(f"Item {item.temp_id} has no payload for _prepare_llm_input in {self.stage_name}.")
            # Este caso ya debería ser gestionado antes por handle_missing_payload o skip_if_terminal_error,
            # pero es una salvaguarda.
            return json.dumps({"error": "No item payload available."})

        input_payload = {
            "item_id": str(item.payload.item_id),
            "item_payload": item.payload.model_dump(mode="json"),
            "problems": [p.model_dump(mode="json") for p in relevant_problems_to_fix]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)


    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal.
        Modificada para procesar ítems con hallazgos de severidad 'error'
        o que fallaron la etapa 'validate_logic'.
        """
        self.logger.info(f"Starting {self.stage_name} for {len(items)} items.")

        items_to_process = []
        for item in items:
            # Skip items already in a terminal error state
            if item.status == "fatal_error":
                self.logger.debug(f"Skipping item {item.temp_id} in {self.stage_name} due to prior fatal status.")
                continue

            # Check if validate_logic failed (original condition for this refiner)
            is_logic_fail = item.status.endswith(".fail") and item.status.startswith("validate_logic")

            # Check if there are any 'error' severity findings present for this item
            # regardless of its current status, to ensure they get a chance to be fixed.
            has_error_findings_to_fix = any(f.severity == "error" for f in item.findings)

            # Process if validate_logic failed OR if there are any error severity findings to fix
            if is_logic_fail or has_error_findings_to_fix:
                items_to_process.append(item)
            else:
                self.logger.debug(f"Item {item.temp_id} skipped by {self.stage_name} (status: {item.status}, no 'error' findings to fix).")


        if items_to_process:
            self.logger.info(f"Found {len(items_to_process)} items matching criteria for {self.stage_name} processing.")
            tasks = [self._process_one_item(item) for item in items_to_process]
            await asyncio.gather(*tasks) # Execute concurrently

        else:
            self.logger.info(f"No items found matching criteria for {self.stage_name} processing.")

        return items


    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado del LLM: reemplaza el payload del ítem por la
        versión refinada y limpia los hallazgos correspondientes.
        """
        # Si _process_llm_result es llamado con None, significa que la etapa optimizó y no hizo llamada a LLM.
        if result is None:
            self.logger.info(f"Item {item.temp_id} in {self.stage_name}: No LLM call performed (optimized).")
            # En este caso, no hay correcciones ni cambios de payload.
            # El _set_status ya se habría manejado si el item fue skipped por alguna razón en _process_one_item.
            # Si llegó aquí, significa que no tenía errores que arreglar o fue optimizado.
            return


        # Asegúrate de que el resultado sea del tipo esperado RefinementResultSchema
        if not isinstance(result, RefinementResultSchema):
            self.logger.error(f"Unexpected result type from LLM in {self.stage_name} for item {item.temp_id}.")
            # Marcar como fatal si el esquema de la respuesta del LLM no es el esperado
            self._set_status(item, "fatal", "Error interno: el esquema de la respuesta del LLM no es RefinementResultSchema.")
            return

        # Comprobar la consistencia del item_id antes de aplicar el refinamiento
        # Esta helper ya maneja el set_status internamente si hay un mismatch
        if handle_item_id_mismatch_refinement(
            item, self.stage_name, item.payload.item_id, result.item_id,
            f"{self.stage_name}.fail.id_mismatch",
            "Item ID mismatched in logical correction response."
        ):
            return # Si hubo un mismatch, la helper ya marcó el ítem como fatal.

        # Aplicar el ítem refinado
        item.payload = result.item_refinado

        # Limpiar los findings que el LLM reportó como corregidos
        # Es crucial que el LLM reporte los 'error_code' correctamente en correcciones_realizadas
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes) # Elimina los findings corregidos

        # Actualizar el estado del ítem
        summary = f"Refinamiento lógico aplicado. {len(result.correcciones_realizadas)} correcciones reportadas."
        # Si el LLM no reportó correcciones, asumimos que no había nada que corregir o no lo hizo.
        # El estado de la etapa será 'success' si no hay nuevos errores fatales.
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
