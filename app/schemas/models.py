# app/schemas/models.py

# Eliminado from dataclasses import dataclass, field # Correct, as it's BaseModel
from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any
import json # Necesario para json.loads en parse_json

from pydantic import BaseModel, Field # Importamos Field
# FinalEvaluationSchema no es parte de este archivo, eliminar si no existe
from app.schemas.item_schemas import ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema, FinalEvaluationSchema # CRÍTICO: FinalEvaluationSchema debe importarse si se usa

# @dataclass(slots=True) # Correct, ELIMINADO EL DECORADOR DATACLASS
class Item(BaseModel): # Mantiene herencia de BaseModel
    """Ítem en memoria mientras recorre el pipeline."""

    # Metadatos de tracking (todos con valores por defecto o Optional para no ser posicionales obligatorios)
    # Estos campos van PRIMERO en BaseModel si no son el campo principal del constructor.
    temp_id: UUID = Field(default_factory=uuid4)
    item_id: Optional[UUID] = Field(None)
    status: str = Field("pending")

    findings: List[ReportEntrySchema] = Field(default_factory=list)
    audits: List[AuditEntrySchema] = Field(default_factory=list)
    prompt_v: Optional[str] = Field(None)
    token_usage: Optional[int] = Field(None)
    # final_evaluation: Optional[Any] = Field(None) # Si FinalEvaluationSchema existe, usarlo como tipo
    final_evaluation: Optional[FinalEvaluationSchema] = Field(None) # CRÍTICO: Usar el tipo FinalEvaluationSchema si existe

    # Payload es un campo obligatorio en el constructor y debe ser el último si no tiene default
    payload: ItemPayloadSchema # Este debe ser el último campo obligatorio sin un Field(default=...)


    @classmethod
    def from_payload(cls, payload: ItemPayloadSchema) -> "Item":
        # Ahora el constructor de Item espera 'payload' como argumento posicional o keyword
        return cls(payload=payload)

    @classmethod
    def parse_json(cls, raw_json: str) -> "Item":
        # Este método asume que el JSON de entrada es para un Item completo,
        # incluyendo el payload y los metadatos de tracking.
        # Si raw_json siempre contuviera un dict que mapea a Item completo:
        data = json.loads(raw_json)
        # CRÍTICO: Este **data podría fallar si raw_json no tiene todos los campos del constructor de Item.
        # Es más seguro usar cls.model_validate(data) si Item es un BaseModel.
        # Sin embargo, el flujo actual NO usa este método parse_json.
        return cls(**data) # Revisa si esto es realmente el uso deseado de parse_json


    def to_orm(self) -> Dict[str, Any]:
        """Convierte el objeto Item a un diccionario compatible con el ORM para persistir."""
        # Separamos los findings por severidad al persistir para compatibilidad con la DB.
        db_errors = [f.model_dump() for f in self.findings if f.severity == 'error']
        db_warnings = [f.model_dump() for f in self.findings if f.severity == 'warning']

        return {
            "id": self.item_id,
            "temp_id": str(self.temp_id), # UUID a string para DB
            "status": self.status,
            "payload": self.payload.model_dump(mode="json"), # Serializa el payload a JSON string
            "errors": db_errors, # Mapeamos a la columna errors de la DB
            "warnings": db_warnings, # Mapeamos a la columna warnings de la DB
            "audits": [audit.model_dump() for audit in self.audits], # Convertir a dict para la DB
            "prompt_v": self.prompt_v, # Versión del prompt
            "token_usage": self.token_usage, # Tokens
            "final_evaluation": self.final_evaluation, # Incluir el nuevo campo en la serialización ORM
            # created_at es gestionado por la DB
        }
