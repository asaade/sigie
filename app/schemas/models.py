# app/schemas/models.py

from dataclasses import dataclass, field
from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any

from app.schemas.item_schemas import BaseModel, ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema, FinalEvaluationSchema

@dataclass(slots=True)
class Item(BaseModel):
    """Ítem en memoria mientras recorre el pipeline."""

    payload: ItemPayloadSchema

    # Metadatos de tracking
    temp_id: UUID = field(default_factory=uuid4)
    item_id: Optional[UUID] = None # Asignado por la BD al persistir
    status: str = "pending"
    errors: List[ReportEntrySchema] = field(default_factory=list)
    warnings: List[ReportEntrySchema] = field(default_factory=list)
    audits: List[AuditEntrySchema] = field(default_factory=list)
    prompt_v: Optional[str] = None
    token_usage: Optional[int] = None
    final_evaluation: Optional[FinalEvaluationSchema] = None

    @classmethod
    def from_payload(cls, payload: ItemPayloadSchema) -> "Item":
        return cls(payload=payload)

    @classmethod
    def parse_json(cls, raw_json: str) -> "Item":
        payload = ItemPayloadSchema.model_validate_json(raw_json)
        return cls.from_payload(payload)

    def to_orm(self) -> Dict[str, Any]:
        """Convierte el objeto Item a un diccionario compatible con el ORM para persistir."""
        return {
            "id": self.item_id, # Será el ID de la BD si ya está persistido
            "temp_id": str(self.temp_id), # UUID a string para DB
            "status": self.status,
            "payload": self.payload.model_dump(mode="json"), # Serializa el payload a JSON string
            "errors": [error.model_dump() for error in self.errors],
            "warnings": [warning.model_dump() for warning in self.warnings],
            "audits": [audit.model_dump() for audit in self.audits],
            "prompt_v": self.prompt_v,
            "token_usage": self.token_usage,
        }
