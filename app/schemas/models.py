"""
Dominio interno de SIGIE.
Dataclasses mutables usados dentro del pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any # Agregamos Dict, Any para to_orm

from app.schemas.item_schemas import ItemPayloadSchema, ReportEntrySchema, AuditEntrySchema  # import seguro y ReportEntrySchema, AuditEntrySchema


@dataclass(slots=True)
class Item:
    """Ítem en memoria mientras recorre el pipeline."""

    payload: ItemPayloadSchema

    # ----- metadatos de tracking -----\
    temp_id: UUID = field(default_factory=uuid4)      # antes de persistir
    item_id: Optional[UUID] = None                    # asignado por la BD
    status: str = "pending"                           # ok / invalid_* / …
    errors: List[ReportEntrySchema] = field(default_factory=list) # Usamos el nuevo esquema
    warnings: List[ReportEntrySchema] = field(default_factory=list) # Usamos el nuevo esquema
    audits: List[AuditEntrySchema] = field(default_factory=list) # ¡NUEVO! Lista de entradas de auditoría
    prompt_v: Optional[str] = None                    # versión del prompt usado
    token_usage: Optional[int] = None                 # suma de tokens etapa

    # ----- fábricas / helpers ---------------------------------------------
    @classmethod
    def from_payload(cls, payload: ItemPayloadSchema) -> "Item":
        return cls(payload=payload)

    @classmethod
    def parse_json(cls, raw_json: str) -> "Item":
        payload = ItemPayloadSchema.model_validate_json(raw_json)
        return cls.from_payload(payload)

    # Convertir al ORM para persistir (ejemplo con SQLAlchemy)
    def to_orm(self) -> Dict[str, Any]: # Cambiado el tipo de retorno a Dict[str, Any]
        # La importación real de 'app.db.models' debería ocurrir en el servicio de persistencia,
        # no directamente aquí, para evitar dependencias circulares.
        # Por ahora, devolvemos un dict que simula el ORM para mantener la compatibilidad.
        # Si usas SQLAlchemy, la conversión real se hará en el servicio.

        # Simulación de la serialización para el ORM
        return {
            "id": self.item_id,
            "payload": self.payload.model_dump(mode="json"),
            "errors": [error.model_dump() for error in self.errors],
            "warnings": [warning.model_dump() for warning in self.warnings],
            "audits": [audit.model_dump() for audit in self.audits], # Convertir a dict para la BD
            "temp_id": str(self.temp_id),
            "status": self.status,
            "prompt_v": self.prompt_v,
            "token_usage": self.token_usage,
            # Añadir otros campos si el modelo ORM los tiene
        }
