# app/pipelines/builtins/persist.py

from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional # Optional es necesario para el type hint de db

from ..registry import register
from app.schemas.models import Item # Nuestro modelo de dominio
from app.db import crud # Importa la capa CRUD
from app.pipelines.abstractions import BaseStage # CRÍTICO: Importamos BaseStage

# update_item_status_and_audit no se importa directamente aquí, lo usa _set_status de BaseStage

logger = logging.getLogger(__name__)

@register("persist")
class PersistStage(BaseStage): # CRÍTICO: Convertido a clase que hereda de BaseStage
    """
    Etapa final del pipeline que persiste el estado de todos los ítems
    en la base de datos utilizando la capa de servicio CRUD.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal de la etapa de persistencia.
        Guarda los ítems que han sido finalizados con éxito.
        """
        self.logger.info(f"Starting persistence stage for {len(items)} items.")

        db_session = self.ctx.get("db") # Obtener la sesión de DB del contexto

        if not db_session:
            self.logger.error(f"Database session not found in context for {self.stage_name} stage. Skipping.")
            for item in items:
                # Si no hay sesión DB, marcamos como fallo de configuración
                self._set_status(item, "fail.nodb_session", "Database session not found in context.")
            return items

        if not items:
            self.logger.info(f"No items to process in {self.stage_name} stage. Skipping.")
            return items

        self.logger.info(f"Attempting to persist {len(items)} items to the database...")
        try:
            # La capa crud se encarga de la lógica de guardar y comitear.
            crud.save_items(db=db_session, items=items)

            # Tras un commit exitoso, actualizamos el estado de cada ítem en memoria.
            for item in items:
                # Solo marcamos éxito si el ítem no estaba ya en un estado de fallo terminal.
                if not item.status.endswith((".fail", ".error")):
                    self._set_status(item, "success", "Item state successfully saved to the database.")
                else: # Si ya tenía un error, solo auditamos que se intentó persistir.
                    self._set_status(item, "skipped_persist_with_prior_fail", "Item not finalized; persistence skipped but audited.")

            self.logger.info(f"Successfully persisted {len(items)} items.")

        except Exception as e:
            self.logger.critical(f"A critical error occurred during the persistence stage: {e}", exc_info=True)
            # Si la transacción falla, actualizamos el estado para reflejar el error.
            for item in items:
                # Si no está ya en un fallo terminal, lo marcamos con el error de persistencia.
                if not item.status.endswith((".fail", ".error")):
                    self._set_status(item, "fail.dberror", f"Failed to save item to database: {e}")

        return items
