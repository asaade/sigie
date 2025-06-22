# Archivo nuevo: app/db/crud.py

import logging
from typing import List
from sqlalchemy.orm import Session

from . import models as db_models
from app.schemas import models as pydantic_models

logger = logging.getLogger(__name__)

def save_items(db: Session, items: List[pydantic_models.Item]) -> List[db_models.ItemDB]:
    """
    Guarda o actualiza una lista de ítems en la base de datos.

    Esta función toma una lista de objetos Pydantic `Item`, los convierte
    a su representación de modelo SQLAlchemy `ItemDB`, y los persiste
    en la base de datos usando una única transacción.

    Args:
        db: La sesión de base de datos de SQLAlchemy.
        items: Una lista de esquemas Pydantic `Item` a guardar.

    Returns:
        Una lista de los objetos SQLAlchemy `ItemDB` que fueron persistidos.
    """
    db_items = []
    for item_schema in items:
        # La lógica de conversión de Pydantic a SQLAlchemy vive aquí.
        # Los campos complejos como payload, audits, etc., se guardan como JSON.
        db_item = db_models.ItemDB(
            id=item_schema.id,
            temp_id=item_schema.temp_id,
            status=item_schema.status,
            token_usage=item_schema.token_usage,
            payload=item_schema.payload.model_dump() if item_schema.payload else None,
            final_evaluation=item_schema.final_evaluation.model_dump() if item_schema.final_evaluation else None,
            errors=[e.model_dump() for e in item_schema.errors],
            warnings=[w.model_dump() for w in item_schema.warnings],
            audit_trail=[a.model_dump() for a in item_schema.audits]
        )
        # db.merge() intenta encontrar un registro con la misma clave primaria.
        # Si lo encuentra, actualiza sus campos. Si no, crea uno nuevo.
        # Es ideal para operaciones de "guardar progreso".
        merged_item = db.merge(db_item)
        db_items.append(merged_item)

    try:
        db.commit()
        logger.info(f"Successfully saved or updated {len(db_items)} items in the database.")
        # Refresca los objetos para asegurar que tenemos los datos más recientes de la BD.
        for db_item in db_items:
            db.refresh(db_item)
        return db_items
    except Exception as e:
        logger.error(f"Failed to save items to database. Rolling back transaction. Error: {e}", exc_info=True)
        db.rollback()
        raise
