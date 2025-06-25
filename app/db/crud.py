# Archivo actualizado: app/db/crud.py

import logging
from typing import List
from sqlalchemy.orm import Session

from . import models as db_models
from app.schemas import models as pydantic_models

logger = logging.getLogger(__name__)

def save_items(db: Session, items: List[pydantic_models.Item]) -> List[db_models.ItemModel]:
    """
    Guarda o actualiza una lista de ítems en la base de datos.
    """
    db_items = []
    for item_schema in items:

        # ▼▼▼ CAMBIO PRINCIPAL AQUÍ ▼▼▼
        # Usamos el nombre de clase correcto del modelo SQLAlchemy (asumimos que es 'Item')
        db_item_data = {
            "id": item_schema.id,
            "temp_id": item_schema.temp_id,
            "status": item_schema.status,
            "token_usage": item_schema.token_usage,
            "payload": item_schema.payload.model_dump() if item_schema.payload else None,
            "final_evaluation": item_schema.final_evaluation.model_dump() if item_schema.final_evaluation else None,
            "findings": [f.model_dump() for f in item_schema.findings],
            "audit_trail": [a.model_dump() for a in item_schema.audits]
        }

        # Instanciamos el modelo correcto
        db_item = db_models.ItemModel(**db_item_data)

        # db.merge() sigue siendo la estrategia correcta
        merged_item = db.merge(db_item)
        db_items.append(merged_item)

    try:
        db.commit()
        logger.info(f"Successfully saved or updated {len(db_items)} items in the database.")
        for db_item in db_items:
            db.refresh(db_item)
        return db_items
    except Exception as e:
        logger.error(f"Failed to save items to database. Rolling back transaction. Error: {e}", exc_info=True)
        db.rollback()
        raise
