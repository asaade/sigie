# app/pipelines/runner.py

import logging
import inspect  # Necesario para verificar si un objeto es una clase
from typing import Dict, List, Any
import yaml
from sqlalchemy.orm import Session

from app.core.log import logger
from app.pipelines.registry import get as get_stage_from_registry
from app.schemas.models import Item
from app.schemas.item_schemas import UserGenerateParams

# Importamos nuestra nueva clase base para poder verificar la herencia
from app.pipelines.abstractions import BaseStage

async def run(
    pipeline_config_path: str | dict[str, Any],
    user_params: UserGenerateParams,
    *,
    ctx: Dict[str, Any] | None = None,
) -> tuple[List[Item], Dict[str, Any]]:
    """
    Ejecuta un pipeline definido en un archivo YAML de forma lineal,
    instanciando y ejecutando clases de etapa o funciones.
    """
    if isinstance(pipeline_config_path, str):
        with open(pipeline_config_path, 'r', encoding='utf-8') as fp:
            config_dict = yaml.safe_load(fp)
    else:
        config_dict = pipeline_config_path

    stages_cfg = config_dict.get('stages', [])
    if not stages_cfg:
        raise ValueError('Pipeline config without stages')

    ctx = ctx or {}
    ctx.setdefault('reports', {})
    ctx.setdefault('usage_tokens_total', 0)
    # Pasamos los user_params al contexto para que estén disponibles en todas las etapas
    ctx['user_params'] = user_params.model_dump()

    items: List[Item] = [] # La lista de ítems se inicializa vacía

    for stage_config in stages_cfg:
        stage_name = stage_config.get("name")
        params = stage_config.get("params", {})

        if not stage_name:
            logger.warning("Found a stage in pipeline.yml without a 'name'. Skipping.")
            continue

        try:
            stage_executable = get_stage_from_registry(stage_name)
        except KeyError:
            logger.error(f"Stage '{stage_name}' is defined in pipeline.yml but not found in registry. Skipping.")
            continue

        logger.info(f"Executing stage: '{stage_name}'")
        try:
            # ▼▼▼ LÓGICA DE EJECUCIÓN MODIFICADA ▼▼▼

            # Verificamos si lo que obtuvimos del registro es una clase que hereda de BaseStage
            if inspect.isclass(stage_executable) and issubclass(stage_executable, BaseStage):
                # Es una clase: la instanciamos y ejecutamos su método .execute()
                logger.debug(f"Stage '{stage_name}' is a class. Instantiating and executing.")
                stage_instance = stage_executable(stage_name, ctx, params)
                items = await stage_instance.execute(items)

            # Se mantiene la compatibilidad con funciones asíncronas simples
            elif inspect.iscoroutinefunction(stage_executable):
                logger.debug(f"Stage '{stage_name}' is a simple async function. Executing.")
                items = await stage_executable(items=items, ctx=ctx, **params)

            else:
                logger.error(f"Registered object for stage '{stage_name}' is not a valid class or async function. Skipping.")
                continue

            # ▲▲▲ FIN DE LA LÓGICA MODIFICADA ▲▲▲
        except Exception as e:
            logger.error(
                f"A critical error occurred during execution of stage '{stage_name}': {e}",
                exc_info=True,
            )
            # Política de fallo temprano: si una etapa falla catastróficamente, se detiene el pipeline.
            for item in items:
                if not item.status.endswith((".fail", ".error")):
                    item.status = f"{stage_name}.fail.runner_error"
            return items, ctx

    logger.info("Pipeline finished successfully.")
    return items, ctx
