# app/schemas/item_schemas.py

from datetime import date, datetime
from typing import List, Optional, Literal, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, validator

class TipoRecursoVisual(str, Enum):
    GRAFICO = 'grafico'
    TABLA = 'tabla'
    DIAGRAMA = 'diagrama'

class TipoReactivo(str, Enum):
    OPCION_MULTIPLE = "opción múltiple"
    SELECCION_UNICA = "seleccion_unica"
    SELECCION_MULTIPLE = "seleccion_multiple"
    ORDENAMIENTO = "ordenamiento"
    RELACION_ELEMENTOS = "relacion_elementos"

class RecursoVisualSchema(BaseModel):
    tipo: TipoRecursoVisual
    descripcion: str = Field(..., max_length=600)
    alt_text: str = Field(..., max_length=250)
    referencia: HttpUrl
    pie_de_imagen: Optional[str] = Field(None, max_length=300)

    class Config:
        frozen = True

class MetadataSchema(BaseModel):
    idioma_item: str = Field(..., max_length=2)
    area: str
    asignatura: str
    tema: str
    contexto_regional: Optional[str] = None
    nivel_destinatario: str
    nivel_cognitivo: Literal["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"]
    dificultad_prevista: Literal["facil", "media", "dificil"]
    fecha_creacion: date = Field(default_factory=date.today)
    parametro_irt_b: Optional[float] = None
    referencia_curricular: Optional[str] = None
    habilidad_evaluable: Optional[str] = None

    class Config:
        from_attributes = True

class OpcionSchema(BaseModel):
    id: Literal["a", "b", "c", "d"]
    texto: str = Field(..., max_length=140)
    es_correcta: bool = False
    justificacion: str = Field(..., min_length=1, max_length=300)

    class Config:
        from_attributes = True

class ItemPayloadSchema(BaseModel):
    item_id: UUID
    testlet_id: Optional[UUID] = None
    estimulo_compartido: Optional[str] = Field(None, max_length=1500)
    metadata: MetadataSchema
    tipo_reactivo: TipoReactivo
    fragmento_contexto: Optional[str] = Field(None, max_length=500)
    recurso_visual: Optional[RecursoVisualSchema] = None
    enunciado_pregunta: str = Field(..., max_length=250)
    opciones: List[OpcionSchema] = Field(..., min_length=3, max_length=4)
    respuesta_correcta_id: Literal["a", "b", "c", "d"]

    @validator('testlet_id', 'estimulo_compartido', pre=True, always=True)
    def ensure_testlet_fields_consistency(cls, v, values):
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('fragmento_contexto', pre=True, always=True)
    def ensure_fragmento_contexto_consistency(cls, v):
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('recurso_visual', pre=True, always=True)
    def ensure_recurso_visual_consistency(cls, v):
        if isinstance(v, dict) and not v:
            return None
        return v

    class Config:
        from_attributes = True

class ReportEntrySchema(BaseModel):
    code: str = Field(..., max_length=50)
    message: str = Field(..., max_length=500)
    field: Optional[str] = Field(None, max_length=100)
    severity: Literal['error', 'warning']

    class Config:
        frozen = True

class CorrectionEntrySchema(BaseModel):
    field: str = Field(..., description="Campo del ítem que fue modificado (ej. 'enunciado_pregunta', 'opciones[0].texto').")
    error_code: str = Field(..., description="Código de error que motivó la corrección.")
    original: Optional[str] = Field(None, description="Valor original del campo antes de la corrección.")
    corrected: Optional[str] = Field(None, description="Nuevo valor del campo después de la corrección.")
    reason: Optional[str] = Field(None, description="Descripción opcional del agente sobre la razón de la corrección.")

    class Config:
        frozen = True

class AuditEntrySchema(BaseModel):
    stage: str = Field(..., max_length=50, description="Nombre de la etapa/agente que realizó la observación/cambio.")
    timestamp: datetime = Field(default_factory=datetime.now, description="Momento en que se registró la entrada.")
    summary: str = Field(..., max_length=1000, description="Resumen cualitativo de la acción o la observación.")
    corrections: List[CorrectionEntrySchema] = Field(default_factory=list, description="Detalle de las correcciones aplicadas si esta etapa modificó el ítem.")

    class Config:
        frozen = True

class UserGenerateParams(BaseModel):
    n_items: int = Field(1, ge=1, le=5)
    idioma_item: str = "es"
    area: str
    asignatura: str
    tema: str
    nivel_destinatario: str
    nivel_cognitivo: Literal["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"]
    dificultad_prevista: Literal["facil", "media", "dificil"] # Asegúrate de que los valores sean en minúsculas
    tipo_generacion: Literal["item", "testlet"] = "item"
    tipo_reactivo: TipoReactivo = Field(TipoReactivo.OPCION_MULTIPLE)
    habilidad: Optional[str] = None
    referencia_curricular: Optional[str] = None
    recurso_visual: Optional[Dict[str, Any]] = None # Nota: este es para la entrada de parámetros, no el esquema completo de RecursoVisualSchema
    estimulo_compartido: Optional[str] = None
    testlet_id: Optional[UUID] = None
    especificaciones_por_item: Optional[List[Dict[str, Any]]] = None
    parametro_irt_b: Optional[float] = None
    contexto_regional: Optional[str] = None
    fragmento_contexto: Optional[str] = None

    class Config:
        extra = "forbid"

class LogicValidationResultSchema(BaseModel):
    item_id: UUID
    logic_ok: bool
    errors: List[ReportEntrySchema]

    class Config:
        from_attributes = True

class RefinementResultSchema(BaseModel):
    item_id: UUID
    item_refinado: ItemPayloadSchema
    correcciones_realizadas: List[CorrectionEntrySchema] = Field(default_factory=list)
    observaciones_agente: Optional[str] = None

    class Config:
        from_attributes = True

class FinalizationResultSchema(BaseModel):
    item_id: UUID
    final_check_ok: bool
    item_final: Optional[ItemPayloadSchema] = None
    correcciones_finales: List[CorrectionEntrySchema] = Field(default_factory=list)
    final_warnings: List[ReportEntrySchema] = Field(default_factory=list)
    observaciones_finales: Optional[str] = None

    class Config:
        from_attributes = True
