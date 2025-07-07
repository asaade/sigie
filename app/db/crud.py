# app/db/crud.py

import logging
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from . import models as db_models
from app.schemas import models as pydantic_models

logger = logging.getLogger(__name__)

def save_items(db: Session, items: List[pydantic_models.Item]) -> List[db_models.ItemModel]:
    """
    Guarda o actualiza una lista de ítems en la base de datos de forma transaccional.
    Para los campos JSONB, espera objetos Python (dicts/lists), no strings JSON.
    """
    db_items_to_return = []

    for item_pydantic in items:
        item_id_uuid: Optional[uuid.UUID] = item_pydantic.item_id
        temp_id_uuid: uuid.UUID = item_pydantic.temp_id

        # --- PREPARACIÓN DE DATOS PARA JSONB ---
        # Se convierten los modelos Pydantic a diccionarios/listas de Python.
        # NO se usa json.dumps(). SQLAlchemy se encargará de la serialización.
        findings_data = [f.model_dump(mode="json") for f in item_pydantic.findings] if item_pydantic.findings else []
        audits_data = [a.model_dump(mode="json") for a in item_pydantic.audits] if item_pydantic.audits else []
        generation_params_data = item_pydantic.generation_params if item_pydantic.generation_params is not None else {}
        payload_data = item_pydantic.payload.model_dump(mode="json") if item_pydantic.payload else None
        final_evaluation_data = (
            item_pydantic.payload.final_evaluation.model_dump(mode="json")
            if item_pydantic.payload and item_pydantic.payload.final_evaluation
            else None
        )

        # Lógica de "Upsert": buscar para actualizar, o crear si no existe.
        db_item = db.query(db_models.ItemModel).filter_by(id=item_id_uuid).first() if item_id_uuid else None

        if db_item:
            # --- ACTUALIZAR ÍTEM EXISTENTE ---
            logger.debug(f"Updating existing item with ID: {item_id_uuid}")
            db_item.temp_id = temp_id_uuid
            db_item.status = item_pydantic.status.value # Usar .value para el enum
            db_item.token_usage = item_pydantic.token_usage
            db_item.payload = payload_data
            db_item.final_evaluation = final_evaluation_data
            db_item.findings = findings_data
            db_item.audits = audits_data
            db_item.generation_params = generation_params_data
        else:
            # --- CREAR NUEVO ÍTEM ---
            logger.debug(f"Creating new item (temp_id: {temp_id_uuid})")
            db_item = db_models.ItemModel(
                # El 'id' será generado por la DB
                temp_id=temp_id_uuid,
                status=item_pydantic.status.value, # Usar .value para el enum
                token_usage=item_pydantic.token_usage,
                payload=payload_data,
                final_evaluation=final_evaluation_data,
                findings=findings_data,
                audits=audits_data,
                generation_params=generation_params_data,
            )
            db.add(db_item)

        db_items_to_return.append(db_item)

    try:
        # Se realiza el commit para toda la lista de ítems en una sola transacción.
        db.commit()
        logger.info(f"Successfully saved or updated {len(db_items_to_return)} items in the database.")

        # Después del commit, los nuevos ítems tendrán su ID asignado por la DB.
        # Se refrescan los objetos para obtener esos nuevos valores.
        for i, db_item in enumerate(db_items_to_return):
            db.refresh(db_item)
            # Se actualiza el objeto Pydantic original con el ID definitivo.
            items[i].item_id = db_item.id

        return db_items_to_return

    except Exception as e:
        logger.error(f"Failed to save items to the database. Rolling back transaction. Error: {e}", exc_info=True)
        db.rollback()
        raise
