# app/pipelines/builtins/persist.py

from __future__ import annotations
from typing import List

from sqlalchemy.orm import Session
from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.db import crud
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry

@register("persist")
class PersistStage(BaseStage):
    """
    Etapa final del pipeline que persiste el estado de todos los ítems
    en la base de datos utilizando la capa CRUD.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Starting persistence stage for {len(items)} items.")
        if not items:
            return items

        # --- CORRECCIÓN ARQUITECTÓNICA ---
        # Se obtiene la sesión de la base de datos desde el contexto de la etapa,
        # que fue inyectado por el runner al inicio del pipeline.
        db: Session = self.ctx.get("db_session")

        if not db:
            # Este es un error crítico de configuración del pipeline.
            self.logger.critical("No se encontró la sesión de base de datos en el contexto de la etapa. No se puede persistir.")
            for item in items:
                add_revision_log_entry(
                    item=item,
                    stage_name=self.stage_name,
                    status=ItemStatus.FATAL,
                    comment="Error de configuración: La sesión de DB no estaba disponible para la etapa de persistencia."
                )
            return items

        items_to_persist = [item for item in items if item.payload]
        if not items_to_persist:
            self.logger.warning("No items with a payload to persist.")
            return items

        try:
            self.logger.info(f"Attempting to persist {len(items_to_persist)} items to the database...")

            # La capa CRUD se encarga de la transacción.
            # Se le pasa la sesión de DB obtenida del contexto.
            crud.save_items(db=db, items=items_to_persist)

            # Después de una persistencia exitosa, actualiza el estado de cada ítem.
            for item in items_to_persist:
                add_revision_log_entry(
                    item=item,
                    stage_name=self.stage_name,
                    status=ItemStatus.PERSISTENCE_SUCCESS,
                    comment=f"Ítem guardado/actualizado exitosamente en la base de datos con ID: {item.item_id}."
                )

            self.logger.info(f"Successfully persisted {len(items_to_persist)} items.")

        except Exception as e:
            self.logger.critical(f"A critical error occurred during the persistence stage: {e}", exc_info=True)
            # Si la transacción falla (crud.save_items lanza una excepción),
            # actualiza el estado de los ítems afectados en memoria.
            for item in items_to_persist:
                add_revision_log_entry(
                    item=item,
                    stage_name=self.stage_name,
                    status=ItemStatus.FATAL,
                    comment=f"Fallo crítico al guardar ítem en la base de datos: {e}"
                )

        return items
