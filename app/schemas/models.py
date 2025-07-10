# app/schemas/models.py
from __future__ import annotations
import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Dependencias de otros módulos de schemas
from .enums import ItemStatus
from .item_schemas import ItemPayloadSchema, FindingSchema, RevisionLogEntry, CorrectionSchema

class Item(BaseModel):
    """
    El modelo Pydantic que representa el estado de un ítem a lo largo del pipeline.
    Este es un objeto en memoria que se pasa entre etapas.
    """
    # --- Identificadores ---
    item_id: Optional[uuid.UUID] = None  # El ID definitivo de la DB, se rellena al final.
    temp_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    batch_id: str

    # --- Estado y Parámetros ---
    status: ItemStatus = ItemStatus.PENDING
    status_comment: Optional[str] = None
    generation_params: Optional[Dict[str, Any]] = None
    token_usage: int = 0

    # --- Contenido y Metadatos Generados ---
    # Se usan Field(default_factory=list) para asegurar que siempre sean listas
    # y evitar errores con valores None.
    payload: Optional[ItemPayloadSchema] = None
    findings: List[FindingSchema] = Field(default_factory=list)
    audits: List[RevisionLogEntry] = Field(default_factory=list)
    change_log: List[CorrectionSchema] = Field(default_factory=list)

    class Config:
        # Es una buena práctica para manejar tipos complejos como UUID.
        arbitrary_types_allowed = True

# --- SOLUCIÓN AL ERROR ---
# Se llama a model_rebuild() para resolver las referencias de tipos (type hints)
# que Pydantic no pudo resolver durante la inicialización.
# Esto es necesario cuando los modelos están definidos en diferentes archivos
# y se referencian entre sí.
Item.model_rebuild()
