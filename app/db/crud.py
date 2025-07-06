# app/db/crud.py

import logging
import uuid
import json
from typing import List, Optional
from sqlalchemy.orm import Session

from . import models as db_models
from app.schemas import models as pydantic_models

logger = logging.getLogger(__name__)

def save_items(db: Session, items: List[pydantic_models.Item]) -> List[db_models.ItemModel]:
    """
    Guarda o actualiza una lista de ítems en la base de datos.
    Permite que la base de datos genere el ID para nuevos ítems.
    """
    db_items = []
    for item_pydantic in items: # item_pydantic es una instancia de pydantic_models.Item

        # item_id_uuid será None para nuevos ítems, o un UUID si el ítem ya existe (reprocesamiento).
        item_id_uuid: Optional[uuid.UUID] = item_pydantic.item_id
        temp_id_uuid: uuid.UUID = item_pydantic.temp_id # temp_id siempre es generado por la app

        # Preparar datos para el modelo ORM.
        # Las listas de Pydantic models se convierten a JSON strings para columnas JSONB.
        findings_data = [f.model_dump(mode="json") for f in item_pydantic.findings] if item_pydantic.findings else []
        audits_data = [a.model_dump(mode="json") for a in item_pydantic.audits] if item_pydantic.audits else []

        # generation_params es un diccionario, se convierte a JSON string para JSONB.
        generation_params_data = item_pydantic.generation_params if item_pydantic.generation_params is not None else {}

        # payload es un Pydantic model, se convierte a diccionario para JSONB.
        payload_data = item_pydantic.payload.model_dump(mode="json") if item_pydantic.payload else None

        # final_evaluation es un Pydantic model, se convierte a diccionario para JSONB.
        final_evaluation_data = (
            item_pydantic.payload.final_evaluation.model_dump(mode="json")
            if item_pydantic.payload and item_pydantic.payload.final_evaluation
            else None
        )

        db_item = None
        if item_id_uuid: # Si item_id está presente, intentamos actualizar un ítem existente
            existing_db_item = db.query(db_models.ItemModel).filter_by(id=item_id_uuid).first()
            if existing_db_item:
                # Actualizar ítem existente
                existing_db_item.temp_id = temp_id_uuid
                existing_db_item.status = item_pydantic.status
                existing_db_item.token_usage = item_pydantic.token_usage
                existing_db_item.payload = payload_data
                existing_db_item.final_evaluation = final_evaluation_data
                existing_db_item.findings = json.dumps(findings_data)
                existing_db_item.audits = json.dumps(audits_data)
                existing_db_item.generation_params = json.dumps(generation_params_data)

                db_item = db.merge(existing_db_item)
                logger.debug(f"Ítem {item_id_uuid} encontrado y fusionado para actualización.")
            else:
                # Si item_id fue proporcionado pero no encontrado, se trata como un nuevo ítem.
                # La base de datos generará el ID.
                logger.warning(f"Ítem ID {item_id_uuid} proporcionado pero no encontrado en DB. Creando nuevo ítem con ID generado por DB.")

                db_item = db_models.ItemModel(
                    temp_id=temp_id_uuid,
                    status=item_pydantic.status,
                    token_usage=item_pydantic.token_usage,
                    payload=payload_data,
                    final_evaluation=final_evaluation_data,
                    findings=json.dumps(findings_data),
                    audits=json.dumps(audits_data),
                    generation_params=json.dumps(generation_params_data),
                    prompt_v=None,
                )
                db.add(db_item)
                logger.debug(f"Nuevo ítem añadido para inserción con ID generado por DB (ID proporcionado: {item_id_uuid}).")
        else: # item_id_uuid es None, lo que indica un nuevo ítem a ser generado por la DB
            db_item = db_models.ItemModel(
                temp_id=temp_id_uuid,
                status=item_pydantic.status,
                token_usage=item_pydantic.token_usage,
                payload=payload_data,
                final_evaluation=final_evaluation_data,
                findings=json.dumps(findings_data),
                audits=audits_data, # FIX: Audits aquí es una lista de dicts, no necesita json.dumps()
                generation_params=json.dumps(generation_params_data), # generation_params_data es un dict, debe ser JSONB
                prompt_v=None,
            )
            db.add(db_item)
            logger.debug("Nuevo ítem añadido para inserción con ID generado por DB (no se proporcionó ID).")

        db_items.append(db_item)

    try:
        db.commit()
        logger.info(f"Se guardaron o actualizaron {len(db_items)} ítems en la base de datos exitosamente.")

        for i, db_item in enumerate(db_items):
            db.refresh(db_item)
            # Actualizar el objeto Pydantic original con el ID definitivo de la base de datos.
            items[i].item_id = db_item.id
            logger.debug(f"Ítem Pydantic {items[i].temp_id} actualizado con DB ID: {items[i].item_id}")
        return db_items
    except Exception as e:
        logger.error(f"Fallo al guardar ítems en la base de datos. Revirtiendo transacción. Error: {e}", exc_info=True)
        db.rollback()
        raise
