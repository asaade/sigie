# app/schemas/item_schemas.py

from datetime import datetime
from typing import List, Optional, Literal, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, validator, ConfigDict

# --- Definiciones de Enums para tipos restringidos ---
class TipoRecursoVisual(str, Enum):
    GRAFICO = 'grafico'
    TABLA = 'tabla'
    DIAGRAMA = 'diagrama'

class TipoReactivo(str, Enum):
    OPCION_MULTIPLE = "opción múltiple"
    SELECCION_UNICA = "seleccion_unica"
    SELECCION_MULTIPLE = "seleccion_multiple"
    ORDENAMIENTO = "ordenamiento"
    COMPLETAMIENTO = 'completamiento'
    RELACION_ELEMENTOS = "relacion_elementos"

class NivelCognitivoEnum(str, Enum): # Renombrado de Literal a Enum
    RECORDAR = "recordar"
    COMPRENDER = "comprender"
    APLICAR = "aplicar"
    ANALIZAR = "analizar"
    EVALUAR = "evaluar"
    CREAR = "crear"

class DificultadPrevistaEnum(str, Enum): # Renombrado de Literal a Enum
    FACIL = "facil"
    MEDIA = "media"
    DIFICIL = "dificil"

# --- Esquemas para componentes del ítem ---
class RecursoVisualSchema(BaseModel):
    tipo: TipoRecursoVisual
    descripcion: str = Field(..., min_length=1, max_length=600) # Añadido min_length=1 para asegurar contenido
    alt_text: str = Field(..., min_length=1, max_length=250) # Añadido min_length=1 para asegurar contenido
    referencia: HttpUrl
    pie_de_imagen: Optional[str] = Field(None, max_length=300)

    model_config = ConfigDict(frozen=True) # Uso de model_config en lugar de class Config

class MetadataSchema(BaseModel):
    idioma_item: str = Field(..., max_length=2) # Mantener str para flexibilidad de idiomas
    area: str
    asignatura: str
    tema: str
    contexto_regional: Optional[str] = None
    nivel_destinatario: str # Mantener str si los niveles pueden ser arbitrarios
    nivel_cognitivo: NivelCognitivoEnum # Usar el Enum
    dificultad_prevista: DificultadPrevistaEnum # Usar el Enum
    referencia_curricular: Optional[str] = None
    habilidad_evaluable: Optional[str] = None
    fecha_creacion: Optional[datetime] = None # Campo gestionado por el sistema

    model_config = ConfigDict(from_attributes=True)

class OpcionSchema(BaseModel):
    id: Literal["a", "b", "c", "d"]
    texto: str = Field(..., min_length=1, max_length=140) # Ajustado max_length a 140
    es_correcta: bool = False
    justificacion: str = Field(..., min_length=1, max_length=300)

    model_config = ConfigDict(from_attributes=True)

# --- Esquema principal para el payload de un ítem ---
class ItemPayloadSchema(BaseModel):
    item_id: UUID # Usar UUID directamente si ya está importado
    testlet_id: Optional[UUID] = None
    estimulo_compartido: Optional[str] = Field(None, max_length=1500)
    metadata: MetadataSchema
    tipo_reactivo: TipoReactivo
    fragmento_contexto: Optional[str] = Field(None, max_length=500)
    recurso_visual: Optional[RecursoVisualSchema] = None
    enunciado_pregunta: str = Field(..., min_length=1, max_length=250) # Ajustado max_length a 250
    opciones: List[OpcionSchema] = Field(..., min_length=3, max_length=4)
    respuesta_correcta_id: Literal["a", "b", "c", "d"]

    @validator('testlet_id', 'estimulo_compartido', pre=True, always=True)
    def ensure_testlet_fields_consistency(cls, v: Any): # Usar Any para la entrada pre=True
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('fragmento_contexto', pre=True, always=True)
    def ensure_fragmento_contexto_consistency(cls, v: Any):
        if isinstance(v, dict) and not v:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator('recurso_visual', pre=True, always=True)
    def ensure_recurso_visual_consistency(cls, v: Any):
        if isinstance(v, dict) and not v:
            return None
        return v

    model_config = ConfigDict(from_attributes=True)

# --- Esquemas para el flujo del pipeline (hallazgos, correcciones, auditorías) ---
class ReportEntrySchema(BaseModel):
    code: str = Field(..., max_length=150)
    message: str = Field(..., max_length=2000)
    field: Optional[str] = Field(None, max_length=300)
    severity: Literal['fatal', 'error', 'warning']
    fix_hint: Optional[str] = Field(None, max_length=500) # Añadido max_length

    model_config = ConfigDict(frozen=True)

class CorrectionEntrySchema(BaseModel):
    field: str = Field(..., description="Campo del ítem que fue modificado (ej. 'enunciado_pregunta', 'opciones[0].texto').")
    error_code: str = Field(..., description="Código de error que motivó la corrección.")
    original: Optional[str] = Field(None, description="Valor original del campo antes de la corrección.")
    corrected: Optional[str] = Field(None, description="Nuevo valor del campo después de la corrección.")
    reason: str = Field(..., min_length=1, max_length=500, description="Descripción del agente sobre la razón de la corrección.") # HECHO OBLIGATORIO y con max_length

    model_config = ConfigDict(frozen=True)

class AuditEntrySchema(BaseModel):
    stage: str = Field(..., max_length=50, description="Nombre de la etapa/agente que realizó la observación/cambio.")
    timestamp: datetime = Field(default_factory=datetime.now, description="Momento en que se registró la entrada.")
    summary: str = Field(..., max_length=2000, description="Resumen cualitativo de la acción o la observación.")
    corrections: List[CorrectionEntrySchema] = Field(default_factory=list, description="Detalle de las correcciones aplicadas si esta etapa modificó el ítem.")

    model_config = ConfigDict(frozen=True)

class RefinementResultSchema(BaseModel):
    item_id: UUID
    item_refinado: ItemPayloadSchema
    correcciones_realizadas: List[CorrectionEntrySchema] = Field(default_factory=list)
    observaciones_agente: Optional[str] = Field(None, max_length=1000) # Añadido max_length

    model_config = ConfigDict(from_attributes=True)

class ValidationResultSchema(BaseModel):
    is_valid: bool = Field(..., description="Veredicto final de la validación. True si pasa, False si falla.")
    findings: List[ReportEntrySchema] = Field(
        default_factory=list,
        description="Lista de problemas, errores o advertencias encontrados por el LLM."
    )

class FinalEvaluationSchema(BaseModel):
    """
    Define la estructura de la evaluación final emitida por un LLM.
    """
    is_publishable: bool = Field(..., description="Veredicto final sobre si el ítem está listo para ser publicado.")
    score: Optional[float] = Field(None, ge=0, le=10, description="Una puntuación numérica de la calidad general del ítem (0-10).")
    justification: str = Field(..., min_length=1, max_length=1000, description="Un resumen cualitativo que justifica la puntuación y el veredicto.") # Añadido min_length, max_length

    model_config = ConfigDict(frozen=True)

# --- Esquema para la solicitud de generación de ítems (input para el pipeline) ---
class UserGenerateParams(BaseModel):
    n_items: int = Field(1, ge=1, le=5)
    idioma_item: str = "es"
    area: str
    asignatura: str
    tema: str
    nivel_destinatario: str
    nivel_cognitivo: NivelCognitivoEnum # Usar el Enum
    dificultad_prevista: DificultadPrevistaEnum # Usar el Enum
    tipo_generacion: Literal["item", "testlet"] = "item"
    tipo_reactivo: TipoReactivo = Field(TipoReactivo.OPCION_MULTIPLE)
    habilidad: Optional[str] = Field(None, max_length=300) # Añadido max_length
    referencia_curricular: Optional[str] = Field(None, max_length=500) # Añadido max_length
    recurso_visual: Optional[Dict[str, Any]] = Field(None)
    estimulo_compartido: Optional[str] = Field(None, max_length=1500) # Añadido max_length
    testlet_id: Optional[UUID] = Field(None)
    especificaciones_por_item: Optional[List[Dict[str, Any]]] = Field(None)
    contexto_regional: Optional[str] = Field(None, max_length=100) # Añadido max_length
    fragmento_contexto: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid") # Mantenido para validación estricta
