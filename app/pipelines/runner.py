# app/pipelines/runner.py

from __future__ import annotations
import os
import yaml
import logging
from pathlib import Path

from typing import List, Dict, Any, Tuple
from app.core.config import Settings
from app.db.session import get_db
from app.schemas.models import Item, ItemStatus # Ensure ItemStatus is imported
from app.schemas.item_schemas import ItemGenerationParams
from app.pipelines.registry import get as get_stage_from_registry
from app.pipelines.utils.stage_helpers import initialize_items_for_pipeline, add_audit_entry


logger = logging.getLogger(__name__)
settings = Settings()

def _chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """Divide *lst* en *n* chunks casi iguales."""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n) if lst]

async def run(
    pipeline_config_path: str | dict[str, Any],
    user_params: ItemGenerationParams,
    *,
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
    ctx.setdefault('usage_tokens_total', 0)
    ctx['user_params'] = user_params.model_dump()

    db_generator = get_db()
    ctx['db_session'] = next(db_generator)

    items: List[Item] = initialize_items_for_pipeline(user_params)
    if not items:
        logger.warning("Pipeline will not execute: No items initialized based on user parameters.")
        if 'db_session' in ctx and db_generator:
            try:
                db_generator.close()
            except RuntimeError:
                pass
        return [], ctx

    try:
        for stage_config in stages_cfg:
            stage_name = stage_config.get("name")
            params = stage_config.get("params", {})

            if not stage_name:
                logger.warning("Found a stage in pipeline.yml without a 'name'. Skipping.")
                continue

            try:
                StageClass = get_stage_from_registry(stage_name)
            except KeyError:
                logger.error(f"Stage '{stage_name}' is defined in pipeline.yml but not found in registry. Marking all current items as fatal_error.")
                for item in items:
                    if item.status != ItemStatus.FATAL.value: # Compare string to string
                        add_audit_entry(
                            item=item,
                            stage_name=stage_name,
                            status=ItemStatus.FATAL,
                            summary=f"Error de configuración: Etapa '{stage_name}' no encontrada en el registro."
                        )
                return items, ctx

            stage_instance = StageClass(stage_name, ctx, params)

            logger.info(f"Executing stage: '{stage_name}'. Items to process: {len(items)}.")

            try:
                updated_items = await stage_instance.execute(items)
                items = updated_items

                # --- FIX: Compare item.status (string) to ItemStatus.SUCCESS.value (string) ---
                if stage_name == 'generate_items' and not any(item.status == ItemStatus.SUCCESS.value for item in items):
                    logger.critical(f"PIPELINE HALTED: '{stage_name}' stage failed to produce any successful items. The pipeline cannot continue.")
                    for item in items:
                        if item.status != ItemStatus.SUCCESS.value and item.status != ItemStatus.FATAL.value:
                            add_audit_entry(
                                item=item,
                                stage_name=stage_name,
                                status=ItemStatus.FATAL,
                                summary="Etapa de generación no produjo ítems con éxito o hubo un problema crítico."
                            )
                    return items, ctx

                # Check for overall pipeline health after each stage (e.g., if all items are fatal)
                if all(item.status == ItemStatus.FATAL.value for item in items):
                    logger.critical("PIPELINE HALTED: All items in the batch are in a FATAL state. The pipeline cannot continue.")
                    return items, ctx
                # --- END FIX ---

            except Exception as e:
                logger.critical(
                    f"A critical error occurred during execution of stage '{stage_name}': {e}",
                    exc_info=True,
                )
                for item in items:
                    if item.status != ItemStatus.SUCCESS.value and item.status != ItemStatus.FATAL.value:
                        add_audit_entry(
                            item=item,
                            stage_name=stage_name,
                            status=ItemStatus.FATAL,
                            summary=f"Fallo catastrófico en la etapa '{stage_name}': {str(e)}"
                        )
                return items, ctx

        logger.info("Pipeline finished successfully.")
        return items, ctx

    finally:
        if 'db_session' in ctx and db_generator:
            try:
                db_generator.close()
            except RuntimeError:
                pass
