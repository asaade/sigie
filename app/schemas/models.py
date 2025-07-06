# app/schemas/models.py

from __future__ import annotations
import uuid
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, UUID4

# Se importa ItemPayloadSchema aquí para que la clase Item la pueda usar.
from app.schemas.item_schemas import ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema

# Definimos el Enum 'ItemStatus' que faltaba.
# Este Enum define los estados posibles que un ítem puede tener en el pipeline.
class ItemStatus(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAIL = "fail"
    FATAL = "fatal"
    SKIPPED = "skipped"
    SKIPPED_DUE_TO_FATAL_PRIOR = "skipped_due_to_fatal_prior"


class Item(BaseModel):
    """
    Representa un ítem y su estado completo a lo largo del pipeline.
    Este es el objeto principal que se pasa entre las etapas.
    """
    # Identificadores
    temp_id: UUID4 = Field(default_factory=uuid.uuid4) # temp_id sigue siendo generado por la app
    # FIX: item_id ahora es opcional y se asignará después de la persistencia en DB
    item_id: Optional[UUID4] = None
    batch_id: Optional[str] = None

    # Estado y Auditoría
    status: str = Field(default=ItemStatus.PENDING.value)
    findings: List[ReportEntrySchema] = []
    audits: List[AuditEntrySchema] = []

    # Datos
    generation_params: Optional[Dict[str, Any]] = None
    payload: Optional[ItemPayloadSchema] = None
    token_usage: int = 0

    class Config:
        from_attributes = True
