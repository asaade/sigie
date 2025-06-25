# app/pipelines/runner.py

from __future__ import annotations
import os
import yaml
import logging # Aseguramos que logging esté importado
from pathlib import Path # Importado Pathlib Path

from typing import List, Dict, Any, Tuple # Importaciones de typing
# Aseguramos que solo se importen los que se usan directamente
from app.schemas.models import Item
from app.schemas.item_schemas import UserGenerateParams, ReportEntrySchema

from app.pipelines.registry import get as get_stage_from_registry # Renombrado para evitar conflicto con get_stage
from app.pipelines.utils.stage_helpers import initialize_items_for_pipeline, add_audit_entry # Importamos la función helper


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

    if isinstance(pipeline_config_path, (str, bytes, bytearray, os.PathLike, Path)): # Pathlib Path no estaba importado, añadido
        with open(pipeline_config_path, 'r', encoding='utf-8') as fp:
            config_dict = yaml.safe_load(fp)
    else: # Si pipeline_config_path ya es un diccionario
        config_dict = pipeline_config_path # CORREGIDO: Usar pipeline_config_path directamente


    stages_cfg = config_dict.get('stages', [])
    if not stages_cfg:
        raise ValueError('Pipeline config without stages')

    ctx = ctx or {}
    ctx.setdefault('usage_tokens_total', 0)
    ctx['user_params'] = user_params.model_dump()

    # Inicializar ítems usando la función helper
    items: List[Item] = initialize_items_for_pipeline(user_params)
    if not items:
        logger.warning("Pipeline will not execute: No items initialized based on user parameters.")
        return [], ctx

    # --- El resto de la lógica de reintentos y on_fail fue eliminada según la nueva filosofía ---
    # El runner ahora itera linealmente, y las etapas gestionan su propio éxito/fallo.
    # Los ítems con estado "fatal_error" serán saltados por las etapas mismas.

    for stage_config in stages_cfg:
        stage_name = stage_config.get("name")
        params = stage_config.get("params", {})

        if not stage_name:
            logger.warning("Found a stage in pipeline.yml without a 'name'. Skipping.")
            continue

        try:
            # Obtener la clase de la etapa del registro
            stage_class = get_stage_from_registry(stage_name)
        except KeyError:
            logger.error(f"Stage '{stage_name}' is defined in pipeline.yml but not found in registry. Marking all current items as fatal_error.")
            for item in items: # Marcar los ítems existentes como fatal_error si no se encontró la etapa
                if item.status not in ["fatal_error"]: # No sobrescribir si ya está fatal
                    item.status = "fatal_error"
                    item.findings.append( # Usando item.findings
                        ReportEntrySchema(
                            code="PIPELINE_CONFIG_ERROR",
                            message=f"Stage '{stage_name}' not found in registry.",
                            severity="error"
                        )
                    )
                    add_audit_entry( # Usando add_audit_entry
                        item=item,
                        stage_name=stage_name,
                        summary=f"Error de configuración: Etapa '{stage_name}' no encontrada."
                    )
            return items, ctx # Devolver ítems con error fatal de configuración

        # Instanciar la clase de etapa y ejecutar su método .execute()
        # Esto asume que todas las etapas ahora son clases que heredan de BaseStage
        # y que su __init__ acepta (stage_name, ctx, params).
        stage_instance = stage_class(stage_name, ctx, params)

        logger.info(f"Executing stage: '{stage_name}'. Items to process: {len(items)}.")

        try:
            # La ejecución de la etapa ya maneja el filtrado de ítems terminales internamente.
            # Aquí, la etapa modifica la lista 'items' directamente (y los objetos Item dentro).
            items = await stage_instance.execute(items)

            # --- VERIFICACIÓN CRÍTICA para la etapa de generación (AHORA CORRECTA) ---
            # Si la etapa generate_items es la actual y NO HAY NINGÚN ítem marcado como .success
            # después de que se ejecute (lo que indica que no produjo payloads válidos),
            # entonces el pipeline debe detenerse.
            if stage_name == 'generate_items' and not any(item.status.endswith(".success") for item in items):
                logger.critical("PIPELINE HALTED: 'generate_items' stage failed to produce any successful items. The pipeline cannot continue. This often indicates a critical failure in the LLM call or a prompt/schema mismatch.")
                # Asegurar que todos los ítems estén en estado fatal_error si no se generó nada con éxito.
                for item in items:
                    # Si el item no está ya marcado como fail/error, lo marcamos fatal.
                    if not item.status.endswith((".fail", ".error")):
                        item.status = "fatal_error"
                        item.findings.append( # Usando item.findings
                            ReportEntrySchema(
                                code="GEN_NO_SUCCESSFUL_OUTPUT",
                                message="Etapa de generación no produjo ítems con éxito.",
                                severity="error"
                            )
                        )
                        add_audit_entry( # Usando add_audit_entry
                            item=item,
                            stage_name=stage_name,
                            summary="Etapa de generación no produjo ítems exitosos. Error fatal."
                        )
                return items, ctx

        except Exception as e:
            logger.error(
                f"A critical error occurred during execution of stage '{stage_name}': {e}",
                exc_info=True,
            )
            # Política de fallo temprano: si una etapa falla catastróficamente, se marca el estado y se detiene.
            for item in items:
                if not item.status.endswith((".fail", ".error")):
                    item.status = f"{stage_name}.fail.runner_error"
                    item.findings.append( # Usando item.findings
                        ReportEntrySchema(
                            code="PIPELINE_FATAL_ERROR",
                            message=f"Stage '{stage_name}' failed fatally: {str(e)}",
                            severity="error"
                        )
                    )
                    add_audit_entry( # Usando add_audit_entry
                        item=item,
                        stage_name=stage_name,
                        summary=f"Error fatal inesperado en la etapa: {str(e)[:200]}"
                    )
            return items, ctx # Devolver ítems con el error fatal

    logger.info("Pipeline finished successfully.")
    return items, ctx
