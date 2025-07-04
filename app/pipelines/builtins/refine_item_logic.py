# app/pipelines/builtins/refine_item_logic.py

from __future__ import annotations
import json
from typing import Type, List, Optional
from uuid import UUID
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema, ReportEntrySchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    clean_specific_errors,
    handle_item_id_mismatch_refinement
)

# No es necesario importar logging, asyncio aquí si no se usan directamente en este archivo,
# ya que LLMStage los maneja.
# logger = logging.getLogger(__name__) # Si se usa, debe importarse logging.

@register("refine_item_logic")
class RefineLogicStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en los hallazgos
    lógicos (con severidad 'error' o 'fatal') detectados previamente.
    Hereda la orquestación del método 'execute' de LLMStage.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Devuelve el esquema Pydantic para la respuesta del LLM (RefinementResultSchema)."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Incluye el payload del ítem y la lista de hallazgos lógicos a corregir.
        """
        # Filtrar solo los hallazgos de severidad 'error' o 'fatal' que sean lógicos.
        # Asumo que los códigos E07x, E092, etc. son los relevantes para esta etapa.
        relevant_problems_to_fix: List[ReportEntrySchema] = [
            f for f in item.findings
            if f.severity in ['error', 'fatal'] and (f.code.startswith('E07') or f.code.startswith('E09'))
        ]

        # Convertir UUIDs a string para el LLM si es necesario
        # Aunque model_dump(mode="json") ya hace esto, ser explícito no daña.
        item_payload_dict = item.payload.model_dump(mode="json")
        if isinstance(item_payload_dict.get("item_id"), UUID): # Check if it's a UUID object
            item_payload_dict["item_id"] = str(item.payload.item_id)

        input_payload = {
            "item_original": item_payload_dict, # Cambiado a item_original para consistencia con refine_item_content
            "problems": [p.model_dump(mode="json") for p in relevant_problems_to_fix]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado del LLM: reemplaza el payload del ítem por la
        versión refinada y limpia los hallazgos correspondientes.
        """
        # Si el LLM no fue llamado (ej. optimización por llm_input is None en _process_one_item),
        # _process_llm_result es llamado con None.
        if result is None:
            self.logger.info(f"Item {item.temp_id} in {self.stage_name}: No LLM call performed (optimized).")
            # No hay correcciones que aplicar ni estado que cambiar si ya venía bien.
            # El estado ya debe ser success de la etapa anterior.
            # No se necesita llamar a _set_status si no hubo acción.
            return

        # Asegúrate de que el resultado sea del tipo esperado RefinementResultSchema
        if not isinstance(result, RefinementResultSchema):
            self.logger.error(f"Unexpected result type from LLM in {self.stage_name} for item {item.temp_id}. Expected RefinementResultSchema.")
            self._set_status(item, "fatal", "Error interno: el esquema de la respuesta del LLM no es RefinementResultSchema.", corrections=None)
            return

        # Comprobar la consistencia del item_id antes de aplicar el refinamiento
        # result.item_id es string, item.payload.item_id es UUID. Convertir ambos a string para la comparación.
        if handle_item_id_mismatch_refinement(
            item, self.stage_name, str(item.payload.item_id), str(result.item_id),
            f"{self.stage_name}.fail.id_mismatch",
            "Item ID mismatched in logical correction response."
        ):
            return # Si hubo un mismatch, la helper ya marcó el ítem como fatal.

        # Aplicar el ítem refinado
        item.payload = result.item_refinado

        # Limpiar los findings que el LLM reportó como corregidos.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes) # Elimina los findings corregidos

        # Actualizar el registro de auditoría del ítem (el _set_status lo hace)
        # add_audit_entry no se llama directamente aquí.

        # Si el LLM refinador ha añadido un revision_log a la metadata, lo incorporamos.
        # Asumiendo que item.payload.metadata es un objeto MetadataSchema y tiene el campo revision_log
        # Asegurarse de que el campo revision_log exista en MetadataSchema como Optional[List[str]]
        if result.item_refinado.metadata and hasattr(result.item_refinado.metadata, 'revision_log') and result.item_refinado.metadata.revision_log is not None:
            if not hasattr(item.payload.metadata, 'revision_log') or item.payload.metadata.revision_log is None:
                item.payload.metadata.revision_log = [] # Inicializar si no existe
            item.payload.metadata.revision_log.extend(result.item_refinado.metadata.revision_log)
            self.logger.debug(f"Added revision_log entries for item {item.temp_id}.")


        # Marcar el estado de éxito.
        # _set_status es quien llama a update_item_status_and_audit, el cual añade la entrada de auditoría.
        summary = f"Refinamiento lógico aplicado. {len(result.correcciones_realizadas)} correcciones reportadas."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
