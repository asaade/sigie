# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import json
from typing import List # List es suficiente para type hints en este archivo
from uuid import UUID

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import UserGenerateParams, ReportEntrySchema, ItemPayloadSchema
from app.pipelines.abstractions import BaseStage

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import (
    handle_prompt_not_found_error,
    handle_item_id_mismatch_refinement,
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
        user_params = UserGenerateParams(**user_params_dict)
        n_items = user_params.n_items

        try:
            # Asegurarse de que el prompt existe al inicio de la etapa
            _ = load_prompt(self.params.get("prompt", "01_agent_dominio.md"))
        except FileNotFoundError as e:
            # Si el prompt no se encuentra, se marcan todos los ítems como fatal_error
            return handle_prompt_not_found_error(items, self.stage_name, self.params.get("prompt", "01_agent_dominio.md"), e)

        logger.info(f"Starting batch generation of {n_items} items.") # Eliminado f-string innecesario

        # Verificar desalineación inicial de la cantidad de ítems
        if len(items) != n_items:
            summary = f"Desalineación crítica: Esperaba {n_items} ítems pre-inicializados, pero recibí {len(items)}. Abortando generación."
            logger.critical(summary) # Eliminado f-string innecesario
            for item in items: # Marcar todos los ítems como fatal_error si hay desalineación
                self._set_status(item, "fatal_error", summary)
                item.findings.append(ReportEntrySchema(code="E954_GEN_INIT_MISMATCH", message=summary, severity="fatal"))
            return items # Terminar la ejecución de la etapa

        # Preparar los item_ids para el LLM (usa item_id de cada Item inicializado)
        # Esto asegura que el LLM genere payloads con los IDs que el sistema espera.
        llm_input_item_ids = [str(item.item_id) for item in items]

        # Construir el payload completo para el LLM, incluyendo los parámetros del usuario
        llm_input_payload = user_params.model_dump()
        llm_input_payload["n_items"] = n_items
        llm_input_payload["item_ids_a_usar"] = llm_input_item_ids # Asignar los IDs al payload de entrada del LLM

        user_input_content_json = json.dumps(llm_input_payload, ensure_ascii=False, indent=2)

        self.logger.info(f"Calling LLM for batch generation of {n_items} items.") # Eliminado f-string innecesario

        # Llama al LLM para generar los payloads.
        # payloads_list_raw será List[ItemPayloadSchema] si tiene éxito, o None si hay errores.
        payloads_list_raw, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=self.params.get("prompt", "01_agent_dominio.md"),
            user_input_content=user_input_content_json,
            stage_name=self.stage_name,
            item=items[0], # Se pasa el primer ítem para asociar el uso de tokens y errores de LLM.
            ctx=self.ctx,
            expected_schema=List[ItemPayloadSchema], # Se espera una lista de ItemPayloadSchema
            model=self.params.get("model"),
            temperature=self.params.get("temperature"),
            max_tokens=self.params.get("max_tokens"),
            top_k=self.params.get("top_k"),
            top_p=self.params.get("top_p"),
            stop_sequences=self.params.get("stop_sequences"),
            seed=self.params.get("seed")
        )

        # Manejo de errores de la llamada al LLM o del formato de la respuesta
        if llm_errors:
            for item in items:
                self._set_status(item, "fail", f"LLM call or parse failed: {llm_errors[0].message}")
                item.findings.extend(llm_errors) # Añadir los errores del LLM a los findings del ítem.
            return items # Terminar la ejecución de la etapa si hay errores del LLM.

        # Verificar que el LLM devolvió una lista y con el número correcto de ítems
        if not isinstance(payloads_list_raw, list):
            summary = "LLM did not return a list of items as expected."
            for item in items:
                self._set_status(item, "fail", summary)
                item.findings.append(ReportEntrySchema(code="E956_LLM_RESPONSE_FORMAT_INVALID", message=summary, severity="fatal"))
            return items # Terminar si el formato es incorrecto.

        if len(payloads_list_raw) != n_items:
            summary = f"LLM generated {len(payloads_list_raw)} items, but {n_items} were requested."
            for item in items:
                self._set_status(item, "fail", summary)
                item.findings.append(ReportEntrySchema(code="E957_LLM_ITEM_COUNT_MISMATCH", message=summary, severity="fatal"))
            return items # Terminar si la cantidad de ítems no coincide.

        # Si llegamos aquí, payloads_list_raw es una lista válida y del tamaño correcto.
        # Ahora es seguro crear el mapa de payloads.
        payloads_map = {str(p.item_id): p for p in payloads_list_raw}

        successful_generation_count = 0
        for item in items: # Iterar sobre los ítems pre-inicializados
            # Buscar el payload generado por el LLM usando el item_id esperado
            generated_payload = payloads_map.get(str(item.item_id))

            if generated_payload:
                # CRÍTICO: Verificar que el item_id del payload generado coincida
                # con el item_id del objeto Item que fluye por el pipeline.
                # Esto asegura que el LLM no "alucina" un item_id diferente.
                if str(generated_payload.item_id) != str(item.item_id):
                    summary_mismatch = f"LLM returned payload for item_id {generated_payload.item_id} but expected {item.item_id}. Mismatch in batch generation mapping."
                    # Usar el helper para reportar el fallo y marcar el ítem como fatal_error.
                    handle_item_id_mismatch_refinement(
                        item, self.stage_name, item.item_id, generated_payload.item_id,
                        f"{self.stage_name}.fail.id_mismatch", summary_mismatch
                    )
                    # Este ítem falló el mapeo, no se cuenta como exitoso.
                else:
                    item.payload = generated_payload # Asignar el payload generado al ítem
                    item.prompt_v = self.params.get("prompt") # Registrar el prompt usado
                    # Limpiar los findings de errores LLM generados por call_llm_and_parse_json_result
                    # si este ítem fue generado exitosamente y mapeado correctamente.
                    item.findings = [
                        f for f in item.findings
                        if not f.code.startswith(("E901", "E902", "E903", "E904", "E905", "E906", "E907"))
                    ]
                    successful_generation_count += 1
                    self._set_status(item, "success", "Item generated successfully.")
            else:
                # Este caso ocurre si un item_id del input no fue encontrado entre los payloads del LLM.
                summary_not_found = f"LLM did not return a payload for expected item_id {item.item_id}. Mismatch in batch generation mapping."
                # Reportar el fallo y marcar como fatal.
                handle_item_id_mismatch_refinement(
                    item, self.stage_name, item.item_id, UUID("00000000-0000-0000-0000-000000000000"), # ID dummy para 'received'
                    f"{self.stage_name}.fail.mapping_issue", summary_not_found
                )

        if successful_generation_count == n_items:
            self.logger.info(f"Batch generation completed successfully for all {n_items} items.")
        else:
            self.logger.warning(f"Batch generation completed with {successful_generation_count}/{n_items} items successfully generated. Some items failed to map or had ID mismatches.")
            # Si no todos los ítems fueron exitosos, el estado del runner se gestionará
            # por el bloque crítico en runner.py si successful_generation_count es 0.

        return items
