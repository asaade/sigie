# app/schemas/item_schemas.py

from datetime import date, datetime
from typing import List, Optional, Literal
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl

# ------ ENUMS PARA TIPOS FIJOS ------
class TipoRecursoVisual(str, Enum):
    GRAFICO = 'grafico'
    TABLA = 'tabla'
    DIAGRAMA = 'diagrama'

class TipoReactivo(str, Enum):
    OPCION_MULTIPLE = "Opción múltiple"
    OPCION_MULTIPLE_UNICA_CORRECTA = "Opción múltiple con única respuesta correcta"
    # Añade aquí otros tipos de reactivos si los hay

# ------ RECURSO VISUAL ------
class RecursoVisualSchema(BaseModel):
    tipo: TipoRecursoVisual
    descripcion: str = Field(..., max_length=600)
    alt_text: str = Field(..., max_length=250)
    referencia: HttpUrl
    pie_de_imagen: Optional[str] = Field(None, max_length=300)

    class Config:
        frozen = True # Inmutable una vez creado

# ------ METADATOS INCLUIDOS EN PAYLOAD ------
class MetadataSchema(BaseModel):
    idioma_item: str
    area: str
    asignatura: str
    tema: str
    contexto_regional: Optional[str] = None
    nivel_destinatario: str
    nivel_cognitivo: str
    dificultad_prevista: str
    fecha_creacion: date = Field(default_factory=date.today)
    parametro_irt_b: Optional[float] = None
    referencia_curricular: Optional[str] = None
    habilidad_evaluable: Optional[str] = None
    tipo_reactivo: TipoReactivo # Usamos el Enum

    class Config:
        from_attributes = True

# ------ OPCIONES ------
class OpcionSchema(BaseModel):
    id: str
    texto: str
    es_correcta: bool = False
    justificacion: str

    class Config:
        from_attributes = True

# ------ PAYLOAD PRINCIPAL DEL ÍTEM ------
class ItemPayloadSchema(BaseModel):
    item_id: UUID # Lo hace parte del payload para que el LLM lo use
    testlet_id: Optional[UUID] = None
    estimulo_compartido: Optional[str] = None
    metadata: MetadataSchema
    enunciado_pregunta: str = Field(..., max_length=2000)
    opciones: List[OpcionSchema] = Field(..., min_length=2, max_length=5) # 2 a 5 opciones
    respuesta_correcta_id: str
    # Campos que el agente de dominio NO debe generar directamente, sino solo si vienen en input
    # especificaciones_por_item: Optional[List[Dict[str, Any]]] = None # No usar directamente en payload generado

    class Config:
        from_attributes = True

# ------ ESQUEMAS DE REPORTE Y AUDITORÍA ------
class ReportEntrySchema(BaseModel):
    code: str = Field(..., max_length=50) # Código alfanumérico del error/advertencia
    message: str = Field(..., max_length=500) # Descripción detallada
    field: Optional[str] = Field(None, max_length=100) # Campo del ítem afectado
    severity: Literal['error', 'warning'] # Nivel de severidad

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
    audits: List[AuditEntrySchema] # Nuevo campo

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
    item_refinado: ItemPayloadSchema # El payload completo del ítem corregido
    correcciones_realizadas: List[CorrectionEntrySchema] = Field(default_factory=list)
    observaciones_agente: Optional[str] = None # Campo para el comentario general del agente

    class Config:
        from_attributes = True

# ------ RESULTADO DE FINALIZACIÓN (AGENTE FINAL) ------
class FinalizationResultSchema(BaseModel):
    item_id: UUID
    final_check_ok: bool
    item_final: Optional[ItemPayloadSchema] = None # El payload final si hubo micro-correcciones
    correcciones_finales: List[CorrectionEntrySchema] = Field(default_factory=list)
    final_warnings: List[ReportEntrySchema] = Field(default_factory=list) # Warnings finales
    observaciones_finales: Optional[str] = None # Nuevo campo para observaciones finales del agente

    class Config:
        from_attributes = True
