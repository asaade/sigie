# app/pipelines/runner.py

from __future__ import annotations
import os
import asyncio
import yaml
import logging
from uuid import UUID

from pathlib import Path
from typing import List, Dict, Any, Tuple
from .registry import get as get_stage
from app.schemas.models import Item
from app.schemas.item_schemas import UserGenerateParams, ReportEntrySchema, AuditEntrySchema # Solo se usan directamente UserGenerateParams, ReportEntrySchema, AuditEntrySchema

from app.pipelines.utils.stage_helpers import initialize_items_for_pipeline # Importar la función helper

logger = logging.getLogger(__name__)

def _chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """Divide *lst* en *n* chunks casi iguales."""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n) if lst]

async def run(
    pipeline_config_path: str | dict[str, Any],
    user_params: UserGenerateParams,
    *,
    ctx: Dict[str, Any] | None = None,
) -> Tuple[List[Item], Dict[str, Any]]:

    if isinstance(pipeline_config_path, (str, bytes, bytearray, os.PathLike, Path)):
        with open(pipeline_config_path, 'r', encoding='utf-8') as fp:
            config_dict = yaml.safe_load(fp)
    else:
        config_dict = pipeline_config_path # Corregido

    stages_cfg = config_dict.get('stages', [])
    if not stages_cfg:
        raise ValueError('Pipeline config without stages')

    ctx = ctx or {}
    ctx.setdefault('reports', {})
    ctx.setdefault('usage_tokens_total', 0)

    # CRÍTICO: Inicializar ítems usando la nueva función helper
    items: List[Item] = initialize_items_for_pipeline(user_params)

    refinement_attempts: Dict[UUID, Dict[str, int]] = {item.temp_id: {} for item in items}

    stage_idx = 0
    while stage_idx < len(stages_cfg):
        spec = stages_cfg[stage_idx]
        stage_name = spec['name']
        stage_params = {k: v for k, v in spec.items() if k != 'name'}

        stage = get_stage(stage_name)
        ctx.setdefault('params', {})[stage_name] = stage_params

        logger.info(f"Executing stage: '{stage_name}'")

        current_items_to_process = [
            item for item in items
            if item.status != "fatal_error"
        ]

        if not current_items_to_process:
            logger.info(f"No items to process for stage '{stage_name}'. Skipping.")
            stage_idx += 1
            continue

        parallel = int(spec.get('print()arallel', 1))

        attempt = 0
        max_stage_attempts = stage_params.get("max_attempts", 1) # max_stage_attempts por stage_name

        while attempt < max_stage_attempts:
            attempt += 1
            logger.debug(f"Stage '{stage_name}' attempt {attempt}/{max_stage_attempts} with {len(current_items_to_process)} items.")

            try:
                if parallel > 1 and len(current_items_to_process) > 1:
                    item_chunks = _chunks(current_items_to_process, parallel)
                    results = await asyncio.gather(
                        *(stage(chunk, ctx) for chunk in item_chunks)
                    )
                    # Aplanar la lista de listas de ítems
                    processed_items = [it for sub in results for it in sub]

                else: # Si parallel = 1 o solo 1 item a procesar
                    processed_items = await stage(current_items_to_process, ctx)

                # Actualizar la lista global de ítems con los procesados en esta iteración
                item_map = {item.temp_id: item for item in items}
                for p_item in processed_items:
                    item_map[p_item.temp_id] = p_item
                items = list(item_map.values())

                on_fail_config = stage_params.get("on_fail")

                if on_fail_config and stage_name.startswith("validate_"):
                    goto_stage_name = on_fail_config["goto"]
                    max_refine_attempts = on_fail_config["max_attempts"]
                    # final_status_on_exhaustion = on_fail_config["final_status_on_exhaustion"] # Ya no se usa directamente aquí

                    # Identificar ítems que han fallado esta validación en esta pasada
                    # Un ítem falla si su status empieza con "failed_" (no "refining_") y no es "fatal_error"
                    # O si específicamente fue marcado como "failed_hard_validation"
                    items_failed_this_validation_run = [
                        item for item in current_items_to_process # Solo ítems que fueron procesados en esta corrida
                        if item.status.startswith("failed_") and item.status != "fatal_error"
                    ]

                    if items_failed_this_validation_run:
                        logger.warning(f"{len(items_failed_this_validation_run)} items failed validation in stage '{stage_name}'. Attempting refinement.")

                        can_refine_any_item = False
                        # Iterar sobre los ítems que fallaron para actualizar sus intentos y decidir el estado
                        for item in items_failed_this_validation_run: # Solo los que fallaron
                            refinement_attempts[item.temp_id][stage_name] = \
                                refinement_attempts[item.temp_id].get(stage_name, 0) + 1

                            current_refine_attempts = refinement_attempts[item.temp_id][stage_name]

                            if current_refine_attempts <= max_refine_attempts:
                                can_refine_any_item = True
                                # Limpiamos errores y advertencias que el refinador debería manejar
                                # La limpieza específica de errores LLM o por código se hace en el refinador
                                item.errors.clear() # Limpia todos los errores para la revalidación
                                item.warnings.clear() # Limpia todas las warnings
                                item.status = "refining" # Estado para indicar que va a refinamiento

                            else: # Agotó intentos
                                logger.error(f"Item {item.temp_id} exhausted refinement attempts for stage '{stage_name}'. Marking as fatal_error.")
                                item.status = "fatal_error" # Simplificado: Marcar como fatal_error
                                item.audits.append(
                                    AuditEntrySchema(
                                        stage=stage_name,
                                        summary=f"Agente refinador agotó intentos ({max_refine_attempts}) para errores de '{stage_name}'. Marcado como fatal_error."
                                    )
                                )

                        if can_refine_any_item: # Si al menos un ítem puede ser refinado, ir al stage de refinamiento
                            try:
                                goto_stage_idx = next(i for i, s in enumerate(stages_cfg) if s['name'] == goto_stage_name)
                                stage_idx = goto_stage_idx # Mover el índice a la etapa de refinamiento
                                break # Romper el bucle de reintentos y volver al bucle principal de etapas (para ejecutar goto_stage_name)
                            except StopIteration:
                                logger.error(f"Goto stage '{goto_stage_name}' not found in pipeline config. Items that failed '{stage_name}' will retain their failed status.")
                                # Si la etapa 'goto' no se encuentra, los ítems fallidos no pueden ser refinados.
                                # Se marcan como fatal_error para detener su procesamiento.
                                for item in items_failed_this_validation_run: # Solo los que fallaron y necesitan este manejo
                                    if item.status != "fatal_error": # Solo si no ha sido marcado ya por agotamiento
                                        item.status = "fatal_error"
                                        item.audits.append(
                                            AuditEntrySchema(
                                                stage=stage_name,
                                                summary=f"Fallo de validación en '{stage_name}'. No se encontró etapa de refinamiento '{goto_stage_name}'. Marcado como fatal_error."
                                            )
                                        )
                                stage_idx += 1 # Avanzar a la siguiente etapa principal
                                break
                        else: # Ningún ítem necesita más refinamiento (todos agotaron intentos o ya estaban terminales)
                            logger.info(f"All items exhausted refinement attempts for stage '{stage_name}'. Proceeding to next main stage.")
                            stage_idx += 1
                            break
                    else: # Ningún ítem falló esta validación, la etapa fue exitosa.
                        stage_idx += 1
                        break
                else: # La etapa no tiene configuración on_fail, o no es una etapa de validación.
                    stage_idx += 1
                    break
            except Exception as exc: # Manejo de errores fatales en la ejecución de la etapa
                logger.error(f"Fatal error during stage '{stage_name}' (attempt {attempt}): {exc}", exc_info=True)
                # Marcar los ítems procesados en esta corrida como fatal_error
                for item in current_items_to_process:
                    item.status = "fatal_error"
                    item.errors.append(ReportEntrySchema(
                        code="PIPELINE_FATAL_ERROR",
                        message=f"Stage '{stage_name}' failed fatally: {str(exc)}",
                        severity="error"
                    ))
                    item.audits.append(
                        AuditEntrySchema(
                            stage=stage_name,
                            summary=f"Error fatal inesperado en la etapa: {str(exc)[:200]}"
                        )
                    )
                break # Romper el bucle de reintentos y marcar los ítems como fatales.
        else: # Este else se ejecuta si el bucle 'while attempt' completó todas las iteraciones sin un 'break'
            # Esto significa que la etapa principal (no de refinamiento) agotó sus intentos, si los tuviera.
            # Los ítems deberían tener sus estados de fallo ya establecidos por la lógica de on_fail, o por la etapa misma.
            logger.warning(f"Stage '{stage_name}' exhausted its own defined max_attempts ({max_stage_attempts}).")
            # Los ítems que llegaron a este punto deberían haber sido marcados como fatal_error por la lógica de agotamiento
            # o si la etapa es no-validación, mantienen su status.
            stage_idx += 1 # Avanzar a la siguiente etapa principal

    logger.info("Pipeline execution completed.")
    return items, ctx
