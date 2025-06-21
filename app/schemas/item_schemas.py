# app/schemas/item_schemas.py

from datetime import date, datetime
from typing import List, Optional, Literal, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, validator

# ------ ENUMS PARA TIPOS FIJOS ------
class TipoRecursoVisual(str, Enum):
    GRAFICO = 'grafico'
    TABLA = 'tabla'
    DIAGRAMA = 'diagrama'

class TipoReactivo(str, Enum):
    # Alineado con item_schema_v1.json
    OPCION_MULTIPLE = "opción múltiple"
    SELECCION_UNICA = "seleccion_unica"
    SELECCION_MULTIPLE = "seleccion_multiple"
    ORDENAMIENTO = "ordenamiento"
    RELACION_ELEMENTOS = "relacion_elementos"

# ------ RECURSO VISUAL ------
class RecursoVisualSchema(BaseModel):
    tipo: TipoRecursoVisual
    descripcion: str = Field(..., max_length=600)
    alt_text: str = Field(..., max_length=250)
    referencia: HttpUrl # Pydantic valida formato URL
    pie_de_imagen: Optional[str] = Field(None, max_length=300)

    class Config:
        frozen = True # Inmutable una vez creado

# ------ METADATOS INCLUIDOS EN PAYLOAD ------
class MetadataSchema(BaseModel):
    idioma_item: str = Field(..., max_length=2) # Añadido max_length por consistencia
    area: str
    asignatura: str
    tema: str
    contexto_regional: Optional[str] = None
    nivel_destinatario: str
    nivel_cognitivo: Literal["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"] # Usar Literal para enums de string
    dificultad_prevista: Literal["facil", "media", "dificil"] # Usar Literal
    fecha_creacion: date = Field(default_factory=date.today) # Se mantiene default_factory para generación automática si no se provee
    parametro_irt_b: Optional[float] = None
    referencia_curricular: Optional[str] = None
    habilidad_evaluable: Optional[str] = None
    # No se incluye tipo_reactivo aquí, ya que el JSON Schema v1 lo tiene a nivel raíz

    class Config:
        from_attributes = True

# ------ OPCIONES ------
class OpcionSchema(BaseModel):
    id: Literal["a", "b", "c", "d"] # Limitar los IDs a los del esquema
    texto: str = Field(..., max_length=140) # Alineado con item_schema_v1.json
    es_correcta: bool = False
    justificacion: str = Field(..., min_length=1, max_length=300) # Alineado con prompt ("no vacía") y item_schema_v1.json (max_length)

    class Config:
        from_attributes = True

# ------ PAYLOAD PRINCIPAL DEL ÍTEM ------
class ItemPayloadSchema(BaseModel):
    item_id: UUID # Pydantic valida formato UUID v4
    testlet_id: Optional[UUID] = None # UUID para testlet_id
    estimulo_compartido: Optional[str] = Field(None, max_length=1500) # Alineado con item_schema_v1.json
    metadata: MetadataSchema
    tipo_reactivo: TipoReactivo # Alineado con el enum y item_schema_v1.json
    fragmento_contexto: Optional[str] = Field(None, max_length=500) # El JSON Schema sugiere < 75 palabras, aquí pongo un max_length razonable
    recurso_visual: Optional[RecursoVisualSchema] = None # Puede ser nulo o un objeto RecursoVisualSchema
    enunciado_pregunta: str = Field(..., max_length=250) # Alineado con item_schema_v1.json
    opciones: List[OpcionSchema] = Field(..., min_length=3, max_length=4) # Alineado con item_schema_v1.json y prompt

    respuesta_correcta_id: Literal["a", "b", "c", "d"] # ID de la opción correcta, limitado a los IDs válidos

    @validator('testlet_id', 'estimulo_compartido', pre=True, always=True)
    def ensure_testlet_fields_consistency(cls, v, values):
        # Si testlet_id o estimulo_compartido son cadenas vacías, convertirlas a None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('fragmento_contexto', pre=True, always=True)
    def ensure_fragmento_contexto_consistency(cls, v):
        # Si fragmento_contexto es una cadena vacía, convertirla a None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('recurso_visual', pre=True, always=True)
    def ensure_recurso_visual_consistency(cls, v):
        # Si recurso_visual es un diccionario vacío o None, convertirlo a None
        if isinstance(v, dict) and not v:
            return None
        return v

    class Config:
        from_attributes = True

# ------ ESQUEMAS DE REPORTE Y AUDITORÍA ------
class ReportEntrySchema(BaseModel):
    code: str = Field(..., max_length=50)
    message: str = Field(..., max_length=500)
    field: Optional[str] = Field(None, max_length=100)
    severity: Literal['error', 'warning']

    class Config:
        frozen = True

class CorrectionEntrySchema(BaseModel):
    field: str = Field(..., description="Campo del ítem que fue modificado (ej. 'enunciado_pregunta', 'opciones[0].texto').")
    reason: str = Field(..., description="Razón por la cual se realizó la corrección.")
    original: Optional[str] = Field(None, description="Valor original del campo antes de la corrección.")
    corrected: Optional[str] = Field(None, description="Nuevo valor del campo después de la corrección.")

    class Config:
        frozen = True

class AuditEntrySchema(BaseModel):
    stage: str = Field(..., max_length=50, description="Nombre de la etapa/agente que realizó la observación/cambio.")
    timestamp: datetime = Field(default_factory=datetime.now, description="Momento en que se registró la entrada.")
    summary: str = Field(..., max_length=1000, description="Resumen cualitativo de la acción o la observación.")
    corrections: List[CorrectionEntrySchema] = Field(default_factory=list, description="Detalle de las correcciones aplicadas si esta etapa modificó el ítem.")

    class Config:
        frozen = True

# ------ ESQUEMA DE PARÁMETROS DE USUARIO PARA GENERACIÓN ------
class UserGenerateParams(BaseModel):
    n_items: int = Field(1, ge=1, le=5) # n_items es 'cantidad' en el prompt. ge=greater than or equal to, le=less than or equal to
    idioma_item: str = "es"
    area: str
    asignatura: str
    tema: str
    nivel_destinatario: str
    nivel_cognitivo: Literal["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"]
    dificultad_prevista: Literal["facil", "media", "dificil"]
    tipo_generacion: Literal["item", "testlet"] = "item"
    tipo_reactivo: TipoReactivo = Field(TipoReactivo.OPCION_MULTIPLE_UNICA_CORRECTA) # Default a un tipo específico
    habilidad: Optional[str] = None
    referencia_curricular: Optional[str] = None
    recurso_visual: Optional[Dict[str, Any]] = None # Recibe un dict, no un schema completo aquí
    estimulo_compartido: Optional[str] = None
    testlet_id: Optional[UUID] = None
    especificaciones_por_item: Optional[List[Dict[str, Any]]] = None # Lista de diccionarios para specs por ítem

    class Config:
        extra = "forbid" # Asegura que no se pasen parámetros no esperados

# ------ RESULTADOS DE GENERACIÓN ------
class ItemGenerationResultSchema(BaseModel):
    item_temp_id: UUID
    status: str
    errors: List[ReportEntrySchema]
    warnings: List[ReportEntrySchema]
    db_id: Optional[UUID] = None

    class Config:
        from_attributes = True

class GenerateItemsResponse(BaseModel):
    success: bool
    prompt_v: str
    tokens: int
    results: List[ItemGenerationResultSchema]

# ------ ÍTEM ALMACENADO (SINGLE) ------
class ItemGenerated(BaseModel):
    id: UUID
    created_at: datetime
    payload: ItemPayloadSchema
    errors: List[ReportEntrySchema]
    warnings: List[ReportEntrySchema]
    audits: List[AuditEntrySchema]

    class Config:
        from_attributes = True

# ------ ÍTEM RESUMEN (LIST) ------
class ItemSummary(BaseModel):
    id: UUID
    created_at: datetime
    enunciado_pregunta: str
    tipo_reactivo: TipoReactivo

    class Config:
        from_attributes = True

# ------ RESULTADO DE VALIDACIÓN (AGENTE RAZONAMIENTO) ------
class LogicValidationResultSchema(BaseModel):
    item_id: UUID
    logic_ok: bool
    errors: List[ReportEntrySchema]

    class Config:
        from_attributes = True

# ------ RESULTADO DE REFINAMIENTO (AGENTE REFINADOR) ------
class RefinementResultSchema(BaseModel):
    item_refinado: ItemPayloadSchema
    correcciones_realizadas: List[CorrectionEntrySchema] = Field(default_factory=list)
    observaciones_agente: Optional[str] = None

    class Config:
        from_attributes = True

# ------ RESULTADO DE FINALIZACIÓN (AGENTE FINAL) ------
class FinalizationResultSchema(BaseModel):
    item_id: UUID
    final_check_ok: bool
    item_final: Optional[ItemPayloadSchema] = None
    correcciones_finales: List[CorrectionEntrySchema] = Field(default_factory=list)
    final_warnings: List[ReportEntrySchema] = Field(default_factory=list)
    observaciones_finales: Optional[str] = None

    class Config:
        from_attributes = True
