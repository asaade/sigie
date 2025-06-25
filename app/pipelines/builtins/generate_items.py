# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import json
from typing import List # Eliminadas Dict, Any, Type (ya no se usan al nivel superior)
from uuid import UUID, uuid4

from ..registry import register
from app.prompts import load_prompt # CRÍTICO: Re-importado
from app.schemas.models import Item
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams, ReportEntrySchema, MetadataSchema # Eliminadas OpcionSchema, RecursoVisualSchema (usadas en initialize_items_for_pipeline)
from app.pipelines.abstractions import BaseStage

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import ( # Se mantienen solo las helpers llamadas directamente
    handle_prompt_not_found_error,
    clean_item_llm_errors,
    handle_item_id_mismatch_refinement,
    # Eliminadas: add_audit_entry, update_item_status_and_audit, handle_missing_payload (ya no se usan directamente)
)


logger = logging.getLogger(__name__)

@register("generate_items")
class GenerateItemsStage(BaseStage):
    """
    Etapa inicial del pipeline que genera un lote de nuevos ítems desde cero
    en una única y eficiente llamada al LLM.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada. Orquesta la generación por lotes y rellena los ítems de entrada.
        """
        user_params_dict = self.ctx.get("user_params", {})
        # Asumimos que user_params ya es válido gracias a la validación previa en el router y initialize_items_for_pipeline.
        user_params = UserGenerateParams(**user_params_dict) # Deserializa el dict a UserGenerateParams
        n_items = user_params.n_items

        try:
            # self.params.get("prompt") es el nombre del prompt. load_prompt lo carga.
            _ = load_prompt(self.params.get("prompt", "01_agent_dominio.md"))
        except FileNotFoundError as e:
            # handle_prompt_not_found_error ya actualiza el estado de los ítems y los audita.
            return handle_prompt_not_found_error(items, self.stage_name, self.params.get("prompt", "01_agent_dominio.md"), e)


        self.logger.info(f"Starting batch generation of {n_items} items.")

        # CRÍTICO: TRABAJAR DIRECTAMENTE SOBRE LA LISTA 'items' RECIBIDA DEL RUNNER.
        if len(items) != n_items:
            summary = f"Desalineación crítica: Esperaba {n_items} ítems pre-inicializados, pero recibí {len(items)}. Abortando generación."
            self.logger.critical(summary)
            for item in items: # Marcar los ítems existentes como fatales
                # Usamos _set_status de BaseStage para actualizar estado y auditar.
                self._set_status(item, "fatal_error", summary)
                item.findings.append(ReportEntrySchema(code="GEN_INIT_MISMATCH", message=summary, severity="error"))
            # Si la lista está vacía, no podemos marcar nada, pero no hay nada que generar.
            if not items:
                # Crear un item fatal para registrar el error si la lista estaba vacía inicialmente.
                dummy_item = Item(payload=ItemPayloadSchema(item_id=uuid4(), metadata=MetadataSchema(idioma_item="es", area="General", asignatura="General", tema="Conceptos Generales", nivel_destinatario="Todos", nivel_cognitivo="recordar", dificultad_prevista="facil")))
                self._set_status(dummy_item, "fatal_error", summary)
                return [dummy_item]
            return items


        # Preparar el input para el LLM Agente de Dominio.
        llm_input_payload = user_params.model_dump()
        llm_input_payload["n_items"] = n_items

        item_ids_for_llm = [str(item.temp_id) for item in items]

        # Corregido el error de sintaxis y la lógica
        if len(item_ids_for_llm) < n_items:
            for _ in range(n_items - len(item_ids_for_llm)):
                item_ids_for_llm.append(str(uuid4()))
        llm_input_payload["item_ids_a_usar"] = item_ids_for_llm # Asignación corregida

        user_input_content_json = json.dumps(llm_input_payload, ensure_ascii=False, indent=2)

        self.logger.info(f"Calling LLM for batch generation of {n_items} items.")

        # Llamada al LLM y parseo usando la utilidad
        payloads_list_raw, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=self.params.get("prompt", "01_agent_dominio.md"),
            user_input_content=user_input_content_json,
            stage_name=self.stage_name,
            item=items[0], # Se pasa el primer item para registrar tokens/errores de la llamada LLM global
            ctx=self.ctx,
            expected_schema=List[ItemPayloadSchema] # Esperamos una lista de ItemPayloadSchema
        )

        # Manejo de errores de la utilidad (llamada LLM o parseo inicial de la lista)
        if llm_errors:
            for item in items: # Propagar el error a todos los ítems del lote
                self._set_status(item, "fail.llm_error", f"LLM call or parse failed: {llm_errors[0].message}")
                item.findings.extend(llm_errors)
            return items

        # Verificación de formato y conteo de la respuesta del LLM
        if not isinstance(payloads_list_raw, list):
            summary = "LLM did not return a list of items as expected."
            for item in items:
                self._set_status(item, "fail.format_error", summary)
                item.findings.append(ReportEntrySchema(code="LLM_RESPONSE_FORMAT_INVALID", message=summary, severity="error"))
            return items

        if len(payloads_list_raw) != n_items:
            summary = f"LLM generated {len(payloads_list_raw)} items, but {n_items} were requested."
            for item in items:
                self._set_status(item, "fail.count_mismatch", summary)
                item.findings.append(ReportEntrySchema(code="LLM_ITEM_COUNT_MISMATCH", message=summary, severity="error"))
            return items

        # Mapear los payloads recibidos a los ítems pre-inicializados
        payloads_map = {str(p.item_id): p for p in payloads_list_raw}

        successful_generation_count = 0
        for item in items: # Iteramos sobre los ítems que el runner nos pasó
            payload = payloads_map.get(str(item.temp_id))
            if payload:
                item.payload = payload
                item.prompt_v = self.params.get("prompt")
                clean_item_llm_errors(item)
                successful_generation_count += 1
                self._set_status(item, "success", "Item generated successfully.")
            else:
                summary = f"LLM did not return a payload for expected item_id {item.temp_id}. Mismatch in batch generation."
                # handle_item_id_mismatch_refinement ya registra el error y actualiza el estado.
                handle_item_id_mismatch_refinement(
                    item, self.stage_name, item.temp_id, UUID("00000000-0000-0000-0000-000000000000"), # ID ficticio para 'received_id'
                    f"{self.stage_name}.fail.id_mismatch",
                    summary
                )

        if successful_generation_count == n_items:
            self.logger.info(f"Batch generation completed successfully for all {n_items} items.")
        else:
            self.logger.warning(f"Batch generation completed with {successful_generation_count}/{n_items} items successfully generated. Some items failed to map.")

        return items
