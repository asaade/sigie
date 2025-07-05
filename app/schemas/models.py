# app/schemas/models.py

from __future__ import annotations
import uuid
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

# Se importa ItemPayloadSchema aquí para que la clase Item la pueda usar.
from app.schemas.item_schemas import ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema

# Definimos el Enum 'ItemStatus' que faltaba.
# Este Enum define los estados posibles que un ítem puede tener en el pipeline.
class ItemStatus(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAIL = "fail"
    FATAL = "fatal"


class Item(BaseModel):
    """
    Representa un ítem y su estado completo a lo largo del pipeline.
    Este es el objeto principal que se pasa entre las etapas.
    """
    # Identificadores
    temp_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: Optional[str] = None # ID persistente
    batch_id: Optional[str] = None

    # Estado y Auditoría
    status: str = ItemStatus.PENDING.value # Usa el Enum para el valor por defecto
    findings: List[ReportEntrySchema] = []
    audits: List[AuditEntrySchema] = []

    # Datos
    generation_params: Optional[Dict[str, Any]] = None # Parámetros que lo crearon
    payload: Optional[ItemPayloadSchema] = None # El contenido del ítem en sí
    token_usage: int = 0

    class Config:
        # Permite que Pydantic maneje tipos complejos como los de SQLAlchemy.
        from_attributes = True
