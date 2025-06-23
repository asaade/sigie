# app/pipelines/builtins/persist.py

import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.db import crud
# Importamos el helper necesario para la auditoría y actualización de estado
from ..utils.stage_helpers import update_item_status_and_audit

logger = logging.getLogger(__name__)

@register("persist")
async def persist_stage(items: List[Item], ctx: Dict[str, Any], **kwargs: Any) -> List[Item]:
    """
    Etapa final del pipeline que persiste el estado de todos los ítems
    en la base de datos utilizando la capa de servicio CRUD.
    """
    stage_name = "persist"
    db = ctx.get("db")

    if not db:
        logger.error(f"Database session not found in context for {stage_name} stage. Skipping.")
        # Opcionalmente, marcar todos los ítems como fallidos si la BD no está disponible
        for item in items:
            if not item.status.endswith(".fail"):
                update_item_status_and_audit(item, stage_name, f"{stage_name}.fail.nodb", "Database session not found.")
        return items

    if not items:
        logger.info(f"No items to process in {stage_name} stage. Skipping.")
        return items

    logger.info(f"Attempting to persist {len(items)} items to the database...")
    try:
        # La llamada a la capa de servicio se mantiene, ya que es correcta.
        crud.save_items(db=db, items=items)

        # Tras un commit exitoso, actualizamos el estado de cada ítem en memoria.
        for item in items:
            update_item_status_and_audit(
                item,
                stage_name,
                f"{stage_name}.success",
                "Item state successfully saved to the database."
            )
        logger.info(f"Successfully persisted {len(items)} items.")

    except Exception as e:
        logger.critical(f"A critical error occurred during the persistence stage: {e}", exc_info=True)
        # Si la transacción falla, actualizamos el estado para reflejar el error.
        for item in items:
            update_item_status_and_audit(
                item,
                stage_name,
                f"{stage_name}.fail.dberror",
                f"Failed to save item to database: {e}"
            )

    return items
