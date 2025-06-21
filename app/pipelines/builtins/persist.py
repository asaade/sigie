# app/pipelines/builtins/persist.py

import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError # Para manejar errores de base de datos

from ..registry import register
from app.schemas.models import Item # Nuestro modelo de dominio
from app.schemas.item_schemas import ReportEntrySchema
from app.db.session import get_db # Importamos la dependencia para obtener la sesión de DB
from app.db.models import ItemModel # Importamos el modelo de la base de datos

# Importar las nuevas utilidades
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

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
    db_generator = None # Inicializar para asegurar que finally lo vea
    try:
        # Obtener una sesión de base de datos.
        # En un contexto de FastAPI, get_db() es un generador/dependencia.
        # Aquí lo usamos como un generador que debe ser cerrado en finally.
        db_generator = get_db()
        db = next(db_generator) # Obtiene la instancia de la sesión

        for item in items:
            # 1. Saltar ítems que ya están en un estado de error terminal
            if skip_if_terminal_error(item, stage_name):
                continue

            # 2. Solo persistir ítems que estén en estado 'finalized'
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
                # Convertir el objeto de dominio Item a un diccionario para el ORM
                # El método to_orm() de app.schemas.models.Item devuelve un dict compatible
                item_data_for_db = item.to_orm()

                # Crear una instancia del modelo de base de datos ItemModel
                # Los campos JSONB (payload, errors, warnings, audits) serán manejados por SQLAlchemy
                db_item = ItemModel(
                    temp_id=item_data_for_db["temp_id"],
                    status=item_data_for_db["status"],
                    payload=item_data_for_db["payload"],
                    errors=item_data_for_db["errors"],
                    warnings=item_data_for_db["warnings"],
                    audits=item_data_for_db["audits"], # Asumiendo que audits también se guarda como JSONB
                    prompt_v=item_data_for_db["prompt_v"],
                    token_usage=item_data_for_db["token_usage"],
                    # created_at es generado por el servidor o func.now()
                )
                # El 'id' se generará automáticamente por la base de datos
                # No se asigna 'id' aquí, se obtendrá después del commit.

                db.add(db_item)
                db.flush() # Para obtener el ID generado por la DB antes del commit final

                # Asignar el ID definitivo generado por la base de datos al objeto Item en memoria
                item.item_id = db_item.id # Este es el campo UUID final de la DB

                item.status = "persisted"
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Ítem persistido exitosamente en DB con ID: {item.item_id}"
                )
                logger.info(f"Item {item.temp_id} persisted with DB ID: {item.item_id}")

            except SQLAlchemyError as e:
                # Rollback para el ítem actual en caso de error de DB
                # Esto es crucial para no afectar el estado de la sesión para los siguientes ítems
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
                # Otros errores inesperados durante el mapeo o la persistencia
                # No hacemos rollback aquí a menos que sea un SQLAlchemyError
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

        # Intentar el commit final de todas las operaciones exitosas del bucle
        # Esto agrupa todas las adiciones individuales y las guarda de una vez.
        db.commit()
        logger.info("DB commit successful for persist stage.")

    except Exception as e:
        # Esto capturaría errores al obtener la sesión de DB o errores no manejados en el bucle principal.
        # Si un error ocurre aquí (ej. en next(db_generator) o db.commit() falla),
        # afecta a todos los ítems.
        logger.critical(f"Fatal error initializing DB session or during global persistence operations: {e}", exc_info=True)
        if db: # Si la sesión se llegó a obtener, intentar rollback para cualquier cambio pendiente
            db.rollback()
            logger.critical("Global DB rollback performed due to fatal error.")
        # Marcar todos los ítems restantes (que no fueron ya persistidos o saltados) como fatal_error
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
        # Asegurarse de cerrar la sesión de DB si se abrió, incluso si hubo errores
        if db_generator:
            try:
                # get_db es un generador, debemos cerrar el generador.
                # No llamar db.close() directamente, sino cerrar el generador.
                # Si get_db es un context manager, usar 'with get_db() as db:' sería mejor.
                # Asumiendo que .close() es el método para limpiar el generador de get_db.
                db_generator.close()
            except RuntimeError as e: # Catch if generator is already closed etc.
                logger.warning(f"Error closing DB session generator: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during DB session generator close: {e}")


    logger.info("Persistence stage completed for all items.")
    return items
