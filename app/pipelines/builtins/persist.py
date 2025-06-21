# app/pipelines/builtins/persist.py

import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.db.session import get_db
from app.db.models import ItemModel

from ..utils.stage_helpers import ( # Importar las funciones helper
    skip_if_terminal_error,
    add_audit_entry
)

logger = logging.getLogger(__name__)

@register("persist")
async def persist_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de persistencia de ítems en la base de datos.
    Guarda los ítems que han sido finalizados con éxito.
    Refactorizado para usar stage_helpers.
    """
    stage_name = "persist"

    logger.info(f"Starting persistence stage for {len(items)} items.")

    db: Optional[Session] = None
    db_generator = None
    try:
        db_generator = get_db()
        db = next(db_generator)

        for item in items:
            if skip_if_terminal_error(item, stage_name):
                continue

            if item.status != "finalized":
                item.status = "persist_skipped_not_finalized"
                item.warnings.append(
                    ReportEntrySchema(
                        code="PERSIST_NOT_FINALIZED",
                        message=f"El ítem no está en estado 'finalized' y no será persistido como final. Estado actual: {item.status}",
                        severity="warning"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Saltado: ítem no está en estado final ({item.status})."
                )
                logger.warning(f"Item {item.temp_id} skipped in {stage_name}: not finalized.")
                continue

            try:
                item_data_for_db = item.to_orm()

                db_item = ItemModel(
                    temp_id=item_data_for_db["temp_id"],
                    status=item_data_for_db["status"],
                    payload=item_data_for_db["payload"],
                    errors=item_data_for_db["errors"],
                    warnings=item_data_for_db["warnings"],
                    audits=item_data_for_db["audits"],
                    prompt_v=item_data_for_db["prompt_v"],
                    token_usage=item_data_for_db["token_usage"],
                )

                db.add(db_item)
                db.flush()

                item.item_id = db_item.id

                item.status = "persisted"
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Ítem persistido exitosamente en DB con ID: {item.item_id}"
                )
                logger.info(f"Item {item.temp_id} persisted with DB ID: {item.item_id}")

            except SQLAlchemyError as e:
                db.rollback()
                item.status = "persistence_failed_db_error"
                item.errors.append(
                    ReportEntrySchema(
                        code="DB_PERSISTENCE_ERROR",
                        message=f"Error al persistir el ítem en la base de datos: {e}",
                        severity="error"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Fallo de persistencia en DB: {e}"
                )
                logger.error(f"DB persistence failed for item {item.temp_id}: {e}")
            except Exception as e:
                item.status = "persistence_failed_unexpected_error"
                item.errors.append(
                    ReportEntrySchema(
                        code="UNEXPECTED_PERSISTENCE_ERROR",
                        message=f"Error inesperado durante la persistencia: {e}",
                        severity="error"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Error inesperado en persistencia: {e}"
                )
                logger.error(f"Unexpected error during persistence for item {item.temp_id}: {e}")

        db.commit()
        logger.info("DB commit successful for persist stage.")

    except Exception as e:
        logger.critical(f"Fatal error initializing DB session or during global persistence operations: {e}", exc_info=True)
        if db:
            db.rollback()
            logger.critical("Global DB rollback performed due to fatal error.")
        for item in items:
            if item.status not in ["persisted", "persist_skipped_not_finalized", "persistence_failed_db_error", "persistence_failed_unexpected_error"]:
                item.status = "fatal_error_on_persist_stage"
                item.errors.append(
                    ReportEntrySchema(
                        code="GLOBAL_PERSISTENCE_FATAL_ERROR",
                        message=f"Error fatal global en la etapa de persistencia: {e}",
                        severity="error"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Error fatal global en persistencia: {e}"
                )
    finally:
        if db_generator:
            try:
                db_generator.close()
            except RuntimeError as e:
                logger.warning(f"Error closing DB session generator: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during DB session generator close: {e}")

    logger.info("Persistence stage completed for all items.")
    return items
