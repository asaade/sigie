# Archivo actualizado: app/pipelines/builtins/persist.py

import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.db import crud  # <-- Importamos nuestro nuevo módulo CRUD

logger = logging.getLogger(__name__)

@register("persist")
async def persist_stage(items: List[Item], ctx: Dict[str, Any], **kwargs: Any) -> List[Item]:
    """
    Etapa final del pipeline que persiste el estado final de todos los ítems
    en la base de datos utilizando la capa de servicio CRUD.
    """
    db = ctx.get("db")
    if not db:
        logger.error("Database session not found in context for persist stage. Skipping.")
        return items

    if not items:
        logger.info("No items to persist. Skipping database operation.")
        return items

    logger.info(f"Persisting {len(items)} items to the database...")
    try:
        # La etapa ahora solo hace una llamada a la capa de servicio.
        # Toda la complejidad está encapsulada en crud.save_items.
        crud.save_items(db=db, items=items)
        logger.info("All items persisted successfully.")
    except Exception as e:
        # Si la persistencia falla, el error ya fue logueado por la capa CRUD.
        # Aquí solo decidimos cómo manejarlo en el pipeline.
        logger.critical(f"A critical error occurred during the final persistence stage: {e}")
        # Opcionalmente, podríamos actualizar el estado de los ítems en memoria.
        for item in items:
            item.status = "persist.fail"

    return items
