# app/pipelines/builtins/persist.py

from __future__ import annotations
import logging
from typing import List

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
                # Determinar si el ítem ya tiene un finding fatal
                has_fatal_finding_on_arrival = any(f.severity == "fatal" for f in item.findings)

                if has_fatal_finding_on_arrival:
                    # Si el ítem ya tenía un finding fatal antes de llegar aquí,
                    # se ha persistido en su estado fatal.
                    self._set_status(
                        item,
                        "persisted_with_fatal_prior_error", # Nuevo outcome para auditoría
                        "Item con errores fatales previos, guardado en base de datos en su estado actual."
                    )
                elif not item.status.endswith((".fail", ".error")):
                    # Si el ítem llegó sin errores terminales y se guardó con éxito.
                    self._set_status(item, "success", "Item guardado exitosamente en la base de datos.")
                else:
                    # Si el ítem llegó con un error terminal no fatal (e.g., .fail, .error)
                    # y no fue manejado por la lógica de fatal_finding_on_arrival
                    self._set_status(item, "skipped_persist_with_prior_fail", "Ítem no finalizado; persistencia omitida/auditada.")

            self.logger.info(f"Successfully persisted {len(items)} items.")

        except Exception as e:
            self.logger.critical(f"A critical error occurred during the persistence stage: {e}", exc_info=True)
            # Si la transacción falla, actualizamos el estado para reflejar el error.
            for item in items:
                # Si no está ya en un fallo terminal, lo marcamos con el error de persistencia.
                if not item.status.endswith((".fail", ".error")):
                    self._set_status(item, "fail.dberror", f"Fallo al guardar ítem en la base de datos: {e}")

        return items
