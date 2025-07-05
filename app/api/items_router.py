# app/api/items_router.py

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import List

from app.schemas.item_schemas import ItemGenerationParams, GenerationResultSchema
from app.pipelines.runner import run as run_pipeline_async
from app.core.log import logger
from app.db.session import get_db
from app.db import crud

router = APIRouter()

# Función envoltorio para llamar al pipeline con los argumentos correctos.
async def run_pipeline_in_background(params: ItemGenerationParams, db: Session):
    """
    Esta función envuelve la llamada al runner para que pueda ser ejecutada
    correctamente por BackgroundTasks.
    """
    pipeline_config_path = "pipeline.yml"
    try:
        # Llama a la función del runner pasándole el argumento 'ctx' por nombre.
        await run_pipeline_async(
            pipeline_config_path=pipeline_config_path,
            user_params=params,
            ctx={"db_session": db}
        )
    except Exception as e:
        logger.error(f"Error al ejecutar el pipeline en segundo plano: {e}", exc_info=True)


@router.post("/items/generate", response_model=GenerationResultSchema, status_code=202)
async def generate_items(
    params: ItemGenerationParams,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Endpoint para iniciar la generación de ítems en segundo plano.
    """
    logger.info(f"Received generation request for {params.n_items} items.")

    # Añade la función envoltorio a las tareas en segundo plano.
    background_tasks.add_task(run_pipeline_in_background, params, db)

    return {
        "success": True,
        "total_tokens_used": 0,
        "results": [{"message": "Item generation process started successfully in the background."}]
    }


@router.get("/items/{item_id}", response_model=dict)
def get_item(item_id: str, db: Session = Depends(get_db)):
    """
    Endpoint para obtener un ítem específico por su ID.
    """
    logger.info(f"Fetching item with ID: {item_id}")
    db_item = crud.get_item(db, item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item_id": str(db_item.item_id), "status": db_item.status, "payload": db_item.payload}


@router.get("/items", response_model=List[dict])
def get_all_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Endpoint para obtener una lista de todos los ítems.
    """
    items = crud.get_items(db, skip=skip, limit=limit)
    return [{"item_id": str(item.item_id), "status": item.status} for item in items]
