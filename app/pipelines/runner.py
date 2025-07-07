# app/pipelines/runner.py

import yaml
from typing import List, Dict, Any, Optional

from app.schemas.models import Item, ItemStatus
from app.core.log import logger
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import initialize_items_for_pipeline
from app.pipelines.registry import get_full_registry

async def run(
    pipeline_config_path: str,
    user_params: Optional[Dict[str, Any]] = None,
    items_to_process: Optional[List[Item]] = None,
    ctx: Optional[Dict[str, Any]] = None,
):
    """
    Orquesta la ejecución de un pipeline definido en un archivo YAML.
    Recibe el registro de etapas como una dependencia inyectada.
    """
    stage_registry = get_full_registry()

    if ctx is None:
        ctx = {}

    try:
        with open(pipeline_config_path, "r") as f:
            config = yaml.safe_load(f)
        pipeline_stages_config = config.get("stages", [])
        logger.info(f"Pipeline config loaded from '{pipeline_config_path}'. Found {len(pipeline_stages_config)} stages.")
    except FileNotFoundError:
        logger.error(f"Archivo de configuración del pipeline no encontrado en: {pipeline_config_path}")
        return
    except yaml.YAMLError as e:
        logger.error(f"Error al parsear el archivo de configuración del pipeline: {e}")
        return

    if not items_to_process:
        if not user_params:
            logger.error("Se debe proporcionar 'user_params' o 'items_to_process' para ejecutar el pipeline.")
            return
        items = initialize_items_for_pipeline(user_params)
    else:
        items = items_to_process

    if not items:
        logger.warning("No hay ítems para procesar en el pipeline.")
        return

    logger.info(f"--- Starting Pipeline Run for {len(items)} items ---")

    for stage_config in pipeline_stages_config:
        stage_name = stage_config.get("name")
        stage_params = stage_config.get("params", {})
        listen_to_status = stage_config.get("listen_to_status_pattern")

        if not stage_name:
            logger.warning("Configuración de etapa sin nombre, omitiendo.")
            continue

        try:
            stage_class = stage_registry.get(stage_name)
            if not stage_class:
                raise KeyError(f"Stage '{stage_name}' not found in the provided registry.")

            stage_instance: BaseStage = stage_class(stage_name, stage_params, ctx)
        except KeyError as e:
            logger.error(f"Error: {e}")
            continue

        # Filtra los ítems según el patrón de estado.
        items_for_stage = [item for item in items if item.status != ItemStatus.FATAL]
        if listen_to_status:
            items_for_stage = [
                item for item in items_for_stage if item.status.value.startswith(listen_to_status)
            ]

        if not items_for_stage:
            logger.info(f"Omitiendo etapa '{stage_name}': no hay ítems que procesar con el patrón '{listen_to_status}'.")
            continue

        logger.info(f"Executing stage: '{stage_name}'. Items to process: {len(items_for_stage)}.")

        try:
            # Las etapas modifican los objetos Item en su lugar.
            await stage_instance.execute(items_for_stage)
        except Exception as e:
            logger.error(f"Error inesperado durante la ejecución de la etapa '{stage_name}': {e}", exc_info=True)
            for item in items_for_stage:
                item.status = ItemStatus.FATAL
                item.status_comment = f"Error no manejado en la etapa {stage_name}: {e}"

    logger.info("--- Pipeline finished successfully ---")
