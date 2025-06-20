# app/pipelines/runner.py (MODIFICADO)

from __future__ import annotations
import os
import asyncio
import yaml
import logging
from uuid import UUID, uuid4

from pathlib import Path
from typing import List, Dict, Any, Tuple
from .registry import get as get_stage
from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, ItemPayloadSchema, UserGenerateParams # Para inicializar ítems

# Configuración del logger
logger = logging.getLogger(__name__)
# Puedes configurar el nivel y formato aquí si lo necesitas, o centralizarlo.
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

class PipelineError(RuntimeError):
    pass

def _chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """Divide *lst* en *n* chunks casi iguales."""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n) if lst]

async def run(
    pipeline_config_path: str | dict[str, Any], # Renombrado para claridad
    user_params: UserGenerateParams, # Recibirá UserGenerateParams directamente
    *,\
    ctx: Dict[str, Any] | None = None,
) -> Tuple[List[Item], Dict[str, Any]]:

    if isinstance(pipeline_config_path, (str, bytes, bytearray, os.PathLike, Path)):
        with open(pipeline_config_path, 'r', encoding='utf-8') as fp:
            config_dict = yaml.safe_load(fp)
    else:
        config_dict = pipeline_config_path

    stages_cfg = config_dict.get('stages', [])
    if not stages_cfg:
        raise ValueError('Pipeline config without stages')

    ctx = ctx or {}
    ctx.setdefault('reports', {}) # Para reportes generales del pipeline
    ctx.setdefault('usage_tokens_total', 0)

    # Inicialización de ítems: Ahora el runner los crea
    items: List[Item] = []
    # Aquí podríamos inicializar los ítems basándonos en user_params.cantidad
    # Pero para la etapa 'generate', le pasaremos una lista vacía y ella los creará
    # o una lista de 'semillas' con solo el temp_id.
    # Por ahora, para simplificar el flujo inicial, 'generate' recibirá una lista de ítems vacíos
    # y los rellenará. Cada ítem debe tener un temp_id para el mapeo.
    for _ in range(user_params.cantidad):
        items.append(Item(payload=ItemPayloadSchema(item_id=uuid4(), metadata=user_params.metadata))) # Inicializar con metadata y un item_id temporal

    # Mapeo para tracking de intentos de refinamiento por item_id y stage
    # {'item_id': {'validate_hard': 0, 'validate_logic': 0}}
    refinement_attempts: Dict[UUID, Dict[str, int]] = {item.temp_id: {} for item in items}

    # Índice de la etapa actual para control del 'goto'
    stage_idx = 0
    while stage_idx < len(stages_cfg):
        spec = stages_cfg[stage_idx]
        stage_name = spec['name']
        stage_params = {k: v for k, v in spec.items() if k != 'name'}

        stage = get_stage(stage_name)
        ctx.setdefault('params', {})[stage_name] = stage_params

        logger.info(f"Executing stage: '{stage_name}'")

        # Filtra ítems para esta etapa: solo aquellos que no estén en estado final
        current_items_to_process = [
            item for item in items
            if item.status not in ["fatal_error", "failed_hard_validation_after_retries",
                                   "failed_logic_validation_after_retries",
                                   "failed_policy_validation_after_retries",
                                   "final_failed_validation"] # Añadir estados finales de fallo
        ]

        if not current_items_to_process:
            logger.info(f"No items to process for stage '{stage_name}'. Skipping.")
            stage_idx += 1
            continue

        parallel = int(spec.get('parallel', 1))

        attempt = 0
        max_stage_attempts = stage_params.get("max_attempts", 1) # Usado para la etapa principal, no los reintentos de on_fail

        # Bucle para reintentos internos de la etapa (si se define en spec, aunque on_fail es el primario)
        # y para la lógica de refinamiento
        while attempt < max_stage_attempts:
            attempt += 1
            logger.debug(f"Stage '{stage_name}' attempt {attempt}/{max_stage_attempts} with {len(current_items_to_process)} items.")

            try:
                if parallel > 1 and len(current_items_to_process) > 1:
                    item_chunks = _chunks(current_items_to_process, parallel)
                    results = await asyncio.gather(
                        *(stage(chunk, ctx) for chunk in item_chunks)
                    )
                    # Flatten results
                    processed_items = [it for sub in results for it in sub]
                else:
                    processed_items = await stage(current_items_to_process, ctx)

                # Reintegrar los ítems procesados en la lista principal 'items'
                # Esto es crucial para que los cambios se reflejen para las siguientes etapas
                item_map = {item.temp_id: item for item in items}
                for p_item in processed_items:
                    item_map[p_item.temp_id] = p_item
                items = list(item_map.values()) # Actualiza la lista principal de ítems

                # --- Lógica on_fail (después de que una etapa de validación ha corrido) ---
                on_fail_config = stage_params.get("on_fail")

                if on_fail_config and stage_name.startswith("validate_"): # Solo validaciones pueden tener on_fail
                    goto_stage_name = on_fail_config["goto"]
                    max_refine_attempts = on_fail_config["max_attempts"]
                    final_status_on_exhaustion = on_fail_config["final_status_on_exhaustion"]

                    items_failed_this_stage = [
                        item for item in items
                        if item.status.startswith(f"failed_{stage_name.replace('validate_', '')}_validation")
                        or item.status == "failed_hard_validation" # Específico para hard_validation
                    ]

                    if items_failed_this_stage:
                        logger.warning(f"{len(items_failed_this_stage)} items failed validation in stage '{stage_name}'. Attempting refinement.")

                        can_refine_any_item = False
                        items_to_refine = []
                        for item in items_failed_this_stage:
                            refinement_attempts[item.temp_id][stage_name] = \
                                refinement_attempts[item.temp_id].get(stage_name, 0) + 1

                            current_refine_attempts = refinement_attempts[item.temp_id][stage_name]

                            if current_refine_attempts <= max_refine_attempts:
                                items_to_refine.append(item)
                                can_refine_any_item = True
                                # Resetear errores/warnings para que el refinador los resuelva y el validador los reevalúe
                                item.errors.clear()
                                item.warnings.clear()
                                item.status = "refining" # Nuevo estado temporal de refinamiento

                            else:
                                logger.error(f"Item {item.temp_id} exhausted refinement attempts for stage '{stage_name}'. Setting status to '{final_status_on_exhaustion}'.")
                                item.status = final_status_on_exhaustion
                                item.audits.append(
                                    AuditEntrySchema(
                                        stage=stage_name,
                                        summary=f"Agente refinador agotó intentos ({max_refine_attempts}) para errores de '{stage_name}'. Estado final: {final_status_on_exhaustion}."
                                    )
                                )

                        if can_refine_any_item:
                            # Buscar el índice de la etapa a la que saltar (refinador)
                            try:
                                goto_stage_idx = next(i for i, s in enumerate(stages_cfg) if s['name'] == goto_stage_name)

                                if goto_stage_idx < stage_idx:
                                    logger.warning(f"Refinement stage '{goto_stage_name}' is before current stage '{stage_name}'. This could lead to infinite loops. Ensure your pipeline.yml order is correct for 'on_fail' logic.")

                                # Establecer los ítems a ser procesados por la etapa de refinamiento
                                # y saltar el índice del bucle principal para ejecutar el refinador
                                # antes de continuar con la siguiente etapa en el flujo original.
                                # Los ítems que no pueden ser refinados ya tienen su estado final.
                                current_items_to_process = items_to_refine
                                stage_idx = goto_stage_idx # Esto hará que la próxima iteración ejecute el refinador
                                break # Salir del bucle interno de "attempt" y dejar que el while principal continue desde goto_stage_idx

                            except StopIteration:
                                logger.error(f"Goto stage '{goto_stage_name}' not found in pipeline config. Items that failed '{stage_name}' will retain their failed status.")
                                for item in items_failed_this_stage:
                                    if item.status != final_status_on_exhaustion: # Si no fue marcado ya por agotar intentos
                                        item.status = "failed_validation_no_refiner_found"
                                        item.audits.append(
                                            AuditEntrySchema(
                                                stage=stage_name,
                                                summary=f"Fallo de validación en '{stage_name}'. No se encontró etapa de refinamiento '{goto_stage_name}'."
                                            )
                                        )
                                # Si no se encontró la etapa goto, no hay reintento, se pasa a la siguiente etapa normal
                                stage_idx += 1
                                break # Salir del bucle interno de "attempt"
                        else:
                            # Si no se pudo refinar ningún ítem (todos agotaron intentos)
                            logger.info(f"All items exhausted refinement attempts for stage '{stage_name}'. Proceeding to next main stage.")
                            stage_idx += 1 # Avanza a la siguiente etapa normal
                            break # Salir del bucle interno de "attempt"
                    else:
                        # Si no hay ítems que hayan fallado esta validación, la etapa fue exitosa.
                        stage_idx += 1 # Avanza a la siguiente etapa normal
                        break # Salir del bucle interno de "attempt"
                else:
                    # Si la etapa no tiene on_fail config, o no es una validación, simplemente avanza
                    stage_idx += 1
                    break # Salir del bucle interno de "attempt"
            except Exception as exc:
                # Manejo de errores fatales en la ejecución de la etapa
                # Aquí, todos los ítems que estaban siendo procesados por esta llamada de etapa
                # se marcan como fatal_error.
                logger.error(f"Fatal error during stage '{stage_name}' (attempt {attempt}): {exc}", exc_info=True)
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
                            summary=f"Error fatal inesperado en la etapa: {str(exc)[:200]}..."
                        )
                    )
                # Ya que es un error fatal, rompemos el bucle de reintentos
                break # Esto saltará a la siguiente etapa principal o finalizará si ya es la última
        else: # Este else se ejecuta si el bucle 'while attempt' completó todas las iteraciones sin un 'break'
            # Esto significa que la etapa principal (no de refinamiento) agotó sus intentos, si los tuviera.
            # En la mayoría de los casos, la lógica de on_fail gestionará los estados de fallo.
            # Este 'else' es más un resguardo.
            logger.warning(f"Stage '{stage_name}' exhausted its own defined max_attempts ({max_stage_attempts}).")
            # Los ítems deberían tener sus estados de fallo ya establecidos por la lógica de on_fail
            # o por la etapa misma si no es de validación.

    logger.info("Pipeline execution completed.")
    return items, ctx
