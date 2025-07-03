# app/schemas/models.py (Este archivo contendría el modelo Pydantic 'Item' que se usa para las respuestas de la API)

from pydantic import BaseModel, ConfigDict # Importar ConfigDict para Pydantic v2
from typing import List, Optional
from uuid import UUID

from app.schemas.item_schemas import ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema, FinalEvaluationSchema

class Item(BaseModel):
    """
    Modelo Pydantic para el objeto Ítem que fluye a través del pipeline
    y es utilizado para las respuestas de la API.
    """
    temp_id: UUID
    item_id: Optional[UUID] = None
    status: str = "pending"
    payload: Optional[ItemPayloadSchema] = None
    findings: List[ReportEntrySchema] = []
    audits: List[AuditEntrySchema] = []
    prompt_v: Optional[str] = None
    token_usage: Optional[int] = None
    final_evaluation: Optional[FinalEvaluationSchema] = None

    # Configuración de Pydantic para asegurar la inclusión de todos los campos en la serialización JSON
    model_config = ConfigDict(
        exclude_none=False,
        exclude_unset=False,
        populate_by_name=True,
        from_attributes=True
    )
