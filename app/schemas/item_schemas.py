# app/schemas/item_schemas.py

from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, UUID4
from datetime import date, datetime
from enum import Enum

# ---------------------------------------------------------------------------
# Sub-Schemas para la nueva arquitectura del Ítem
# ---------------------------------------------------------------------------

class DominioSchema(BaseModel):
    area: str
    asignatura: str
    tema: str

class AudienciaSchema(BaseModel):
    nivel_educativo: str
    dificultad_esperada: Literal["facil", "media", "dificil"]

class FormatoSchema(BaseModel):
    tipo_reactivo: Literal["cuestionamiento_directo", "completamiento", "ordenamiento", "relacion_elementos"]
    numero_opciones: int

class TipoReactivo(str, Enum):
    """Enum para los tipos de reactivo, para retrocompatibilidad."""
    CUESTIONAMIENTO_DIRECTO = "cuestionamiento_directo"
    COMPLETAMIENTO = "completamiento"
    ORDENAMIENTO = "ordenamiento"
    RELACION_ELEMENTOS = "relacion_elementos"

class ContextoSchema(BaseModel):
    contexto_regional: Optional[str] = None
    referencia_curricular: Optional[str] = None

class ArquitecturaSchema(BaseModel):
    dominio: DominioSchema
    objetivo_aprendizaje: str = Field(..., description="Verbo de Bloom + contenido. La directriz principal del ítem.")
    audiencia: AudienciaSchema
    formato: FormatoSchema
    contexto: Optional[ContextoSchema] = None

class OpcionCuerpoSchema(BaseModel):
    id: str
    texto: str

class CuerpoItemSchema(BaseModel):
    estimulo: Optional[str] = None
    enunciado_pregunta: str
    opciones: List[OpcionCuerpoSchema]

class RetroalimentacionOpcionSchema(BaseModel):
    id: str
    es_correcta: bool
    justificacion: str = Field(..., max_length=500)

class ClaveDiagnosticoSchema(BaseModel):
    respuesta_correcta_id: str
    errores_comunes_mapeados: List[str]
    retroalimentacion_opciones: List[RetroalimentacionOpcionSchema]

class MetadataCreacionSchema(BaseModel):
    fecha_creacion: date
    agente_generador: str
    version: str = "7.0"

class FinalEvaluationSchema(BaseModel):
    is_publishable: bool
    score: float = Field(..., ge=0, le=10)
    justification: str

# ---------------------------------------------------------------------------
# Schema Principal del Payload del Ítem (NUEVA ESTRUCTURA)
# ---------------------------------------------------------------------------

class ItemPayloadSchema(BaseModel):
    # Hacer item_id opcional para que la base de datos lo genere.
    item_id: Optional[UUID4] = None
    arquitectura: ArquitecturaSchema
    cuerpo_item: CuerpoItemSchema
    clave_y_diagnostico: ClaveDiagnosticoSchema
    metadata_creacion: MetadataCreacionSchema
    testlet_id: Optional[UUID4] = None
    final_evaluation: Optional[FinalEvaluationSchema] = None

# ---------------------------------------------------------------------------
# Schemas para la API y el Pipeline Interno
# ---------------------------------------------------------------------------

class ItemGenerationParams(BaseModel):
    dominio: DominioSchema
    objetivo_aprendizaje: str
    audiencia: AudienciaSchema
    formato: FormatoSchema
    contexto: Optional[ContextoSchema] = None
    n_items: int = Field(1, gt=0)
    lote: Optional[dict] = None

class GenerationResultSchema(BaseModel):
    success: bool
    total_tokens_used: int
    results: List[dict]

class ReportEntrySchema(BaseModel):
    code: str
    severity: Literal["info", "warning", "error", "fatal"]
    message: str
    component_id: Optional[str] = None

class ValidationResultSchema(BaseModel):
    is_valid: bool
    findings: List[ReportEntrySchema] = []

class CorrectionSchema(BaseModel):
    error_code: str
    summary_of_correction: str

class RefinementResultSchema(BaseModel):
    item_id: str
    item_refinado: ItemPayloadSchema
    correcciones_realizadas: List[CorrectionSchema]

class AuditEntrySchema(BaseModel):
    """
    Esquema para una entrada individual en el registro de auditoría de un ítem.
    Describe qué etapa se ejecutó, cuándo y cuál fue el resultado.
    """
    stage: str
    timestamp: datetime
    summary: str
    correcciones: List[CorrectionSchema] = []
