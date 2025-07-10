# app/api/items_router.py

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.schemas.item_schemas import (
    BatchStatusResultSchema,
    GenerationResultSchema,
    ItemGenerationParams,
    ItemPayloadSchema,
)
from app.schemas.enums import ItemStatus
from app.schemas.models import Item
from app.pipelines.runner import run as run_pipeline_async
from app.pipelines.utils.stage_helpers import initialize_items_for_pipeline
from app.core.log import logger
from app.db.session import get_db
from app.db import crud

router = APIRouter()


async def run_pipeline_in_background(items: List[Item], db: Session):
    """
    Función envoltorio que ahora obtiene el registro y lo inyecta en el runner.
    """
    try:
        # Obtiene el registro completo de etapas
        await run_pipeline_async(
            pipeline_config_path="pipeline.yml",
            items_to_process=items,
            ctx={"db_session": db},
        )
    except Exception as e:
        logger.error(
            f"Error al ejecutar el pipeline en segundo plano: {e}", exc_info=True
        )


@router.post("/items/generate", response_model=GenerationResultSchema, status_code=202)
async def generate_items(
    params: ItemGenerationParams,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Endpoint para iniciar la generación de ítems en segundo plano.
    Ahora inicializa los ítems y devuelve un batch_id inmediatamente.
    """
    logger.info(f"Received generation request for {params.n_items} items.")

    # 1. Inicializa los ítems ANTES de la tarea en segundo plano.
    initialized_items = initialize_items_for_pipeline(params.model_dump())
    if not initialized_items:
        raise HTTPException(
            status_code=400, detail="Failed to initialize items for the pipeline."
        )

    # 2. Extrae el batch_id del primer ítem (todos tienen el mismo).
    batch_id = initialized_items[0].batch_id

    # 3. Añade la tarea en segundo plano, pasándole la lista de ítems.
    background_tasks.add_task(run_pipeline_in_background, initialized_items, db)

    # 4. Devuelve una respuesta útil y alineada con el nuevo schema.
    return GenerationResultSchema(
        message="Item generation process started successfully in the background.",
        batch_id=batch_id,
        num_items=len(initialized_items),
    )


@router.get("/items/{item_id}", response_model=ItemPayloadSchema)
def get_item(item_id: str, db: Session = Depends(get_db)):
    """
    Endpoint para obtener un ítem específico por su ID.
    Actualizado para devolver el payload completo usando ItemPayloadSchema.
    """
    logger.info(f"Fetching item with ID: {item_id}")

    # Validamos que el item_id sea un UUID válido.
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format.")

    db_item = crud.get_item(db, item_uuid)
    if db_item is None or not db_item.payload:
        raise HTTPException(status_code=404, detail="Item not found or has no payload.")

    # El payload ya es un diccionario/JSON, Pydantic/FastAPI lo validará
    # contra el response_model ItemPayloadSchema.
    return db_item.payload


@router.get("/items/batch/{batch_id}", response_model=BatchStatusResultSchema)
def get_batch_status(batch_id: str, db: Session = Depends(get_db)):
    """
    Obtiene el estado de un lote de generación de ítems.
    Permite al usuario sondear el resultado de su solicitud asíncrona.
    """
    logger.info(f"Fetching status for batch_id: {batch_id}")
    db_items = crud.get_items_by_batch_id(db, batch_id)

    if not db_items:
        raise HTTPException(status_code=404, detail="Batch ID not found.")

    total_items = len(db_items)
    processed_items = sum(1 for item in db_items if item.status != ItemStatus.PENDING.value)
    successful_items = sum(1 for item in db_items if item.status == ItemStatus.PERSISTENCE_SUCCESS.value)
    failed_items = sum(1 for item in db_items if item.status == ItemStatus.FATAL.value)
    is_complete = processed_items == total_items

    results = [
        {"item_id": item.id, "temp_id": item.temp_id, "status": item.status}
        for item in db_items
    ]

    return BatchStatusResultSchema(
        batch_id=batch_id,
        is_complete=is_complete,
        total_items=total_items,
        processed_items=processed_items,
        successful_items=successful_items,
        failed_items=failed_items,
        results=results,
    )


@router.get("/items", response_model=List[dict])
def get_all_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Endpoint para obtener una lista de todos los ítems.
    """
    items = crud.get_items(db, skip=skip, limit=limit)
    # Devuelve una lista simplificada para no sobrecargar la respuesta.
    return [{"item_id": str(item.item_id), "status": item.status} for item in items]
