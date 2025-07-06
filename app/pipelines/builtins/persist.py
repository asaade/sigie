# app/pipelines/builtins/persist.py

from __future__ import annotations
import logging
from typing import List, Dict, Any # Added Dict, Any for robust type hints for ctx
from app.schemas.models import Item, ItemStatus # Import ItemStatus enum
from ..registry import register # Ensure register is imported
from app.db import crud # Importa la capa CRUD
from app.pipelines.abstractions import BaseStage # Importamos BaseStage
from app.db.session import get_db # Import get_db to acquire session if needed

logger = logging.getLogger(__name__)

@register("persist")
class PersistStage(BaseStage):
    """
    Etapa final del pipeline que persiste el estado de todos los ítems
    en la base de datos utilizando la capa de servicio CRUD.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Starting persistence stage for {len(items)} items.")

        # --- FIX: Correctly retrieve db_session from context OR acquire a new one ---
        db_to_use = None
        local_db_generator = None # To manage local session closure in finally block

        # 1. Try to get db_session from context
        db_session_from_ctx = self.ctx.get("db_session")

        if db_session_from_ctx:
            try:
                # Basic check to see if the session is likely still usable
                db_session_from_ctx.connection()
                db_to_use = db_session_from_ctx
                self.logger.debug("Using database session from context for persist stage.")
            except Exception as e:
                self.logger.warning(f"Context DB session appears invalid for persist stage: {e}. Attempting to acquire a new session.")
                # Fall through to acquire new session if context session is bad

        # 2. If no usable session from context, acquire a new one
        if db_to_use is None:
            try:
                local_db_generator = get_db()
                db_to_use = next(local_db_generator)
                self.logger.info("Acquired new database session locally for persist stage.")
            except Exception as e:
                self.logger.error(f"Failed to acquire database session for persist stage: {e}. Skipping persistence for all items.", exc_info=True)
                # If cannot even get a new session, mark all items as FAIL for persistence
                for item in items:
                    # Use ItemStatus.FAIL for this scenario
                    self._set_status(item, ItemStatus.FAIL, f"Persistencia fallida: Sesión de BD no disponible ({e}).")
                return items # Exit if no DB session can be established

        # At this point, db_to_use should be a valid session (or we would have exited)
        if not items:
            self.logger.info(f"No items to process in {self.stage_name} stage. Skipping.")
            return items

        self.logger.info(f"Attempting to persist {len(items)} items to the database...")
        try:
            # The crud layer typically handles saving all items in a list and committing.
            # Ensure crud.save_items is designed for batch saving or call it per item with commit management.
            # Assuming crud.save_items handles the transaction commit for the list.
            crud.save_items(db=db_to_use, items=items) # Pass the items list

            # After successful commit, update the status of each item in memory.
            for item in items:
                # Determine if the item had a FATAL finding from prior stages
                has_fatal_finding_on_arrival = item.status == ItemStatus.FATAL # Direct Enum comparison

                if has_fatal_finding_on_arrival:
                    # If item was already FATAL, it was persisted in its FATAL state.
                    self._set_status(
                        item,
                        ItemStatus.FATAL, # Status remains FATAL
                        "Item con errores fatales previos, guardado en base de datos en su estado actual (FATAL)."
                    )
                # Check for other non-successful states that should not be marked as SUCCESS after persistence
                elif item.status in [ItemStatus.PENDING, ItemStatus.SKIPPED, ItemStatus.FAIL, ItemStatus.SKIPPED_DUE_TO_FATAL_PRIOR]:
                    # These items reached persist stage but were not SUCCESS.
                    # Mark them as persisted with their prior non-SUCCESS status, or log specific outcome.
                    # For simplicity, if not FATAL and not SUCCESS, it's a FAIL for final persistence outcome
                    self._set_status(item, ItemStatus.FAIL, "Ítem no finalizado (con fallos previos), guardado en base de datos.")
                else:
                    # If the item arrived in a SUCCESS state or similar and was persisted.
                    self._set_status(item, ItemStatus.SUCCESS, "Ítem guardado exitosamente en la base de datos.")

            self.logger.info(f"Successfully persisted {len(items)} items.")

        except Exception as e:
            self.logger.critical(f"A critical error occurred during the persistence stage: {e}", exc_info=True)
            # If the transaction fails, update item statuses to reflect the error.
            for item in items:
                # If not already FATAL, mark with persistence error
                if item.status not in [ItemStatus.FATAL, ItemStatus.FAIL, ItemStatus.SKIPPED, ItemStatus.SKIPPED_DUE_TO_FATAL_PRIOR]:
                    self._set_status(item, ItemStatus.FATAL, f"Fallo crítico al guardar ítem en la base de datos: {e}")
                else:
                    # If already in a terminal state, just add an audit entry for persistence attempt failure
                    add_audit_entry(
                        item=item,
                        stage_name=self.stage_name,
                        status=item.status, # Keep original status
                        summary=f"Intento de persistencia fallido debido a error crítico: {e}",
                        corrections=[] # No corrections for persistence failure
                    )

        finally:
            # Ensure local_db_generator is closed if it was opened locally within this stage
            if local_db_generator:
                try:
                    local_db_generator.close()
                    self.logger.debug("Closed local database session for persist stage.")
                except RuntimeError:
                    pass # Generator already closed or not started

        return items
