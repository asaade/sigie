# app/schemas/item_schemas.py

from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, UUID4

# Se importa ItemStatus desde su archivo dedicado para evitar ciclos.
from .enums import ItemStatus
import uuid



class FormatoSchema(BaseModel):
    """
    Valores válidos:

    Para tipo de reactivo:
    * A. Cuestionamiento Directo (`cuestionamiento_directo`): Formato estándar con `estimulo` (opcional) y `enunciado_pregunta`.
    * B. Completamiento (`completamiento`): La base contiene `_______`. Las opciones proveen las palabras, separadas por `coma y espacio` si son varias.
    * C. Ordenamiento (`ordenamiento`): El `estimulo` presenta una lista numerada (`1.`, `2.`). Las opciones son permutaciones numéricas (`3, 1, 2`).
    * D. Relación de Elementos (`relacion_elementos`): El `estimulo` es una tabla Markdown con dos columnas (`1.` y `a)`). Las opciones son pares de correspondencia (`1b, 2a`).

    Para número de opciones:
    3 o 4
"""
    tipo_reactivo: str
    numero_opciones: int = Field(4, gt=2, le=4, description="Número de opciones por reactivo.")

# --- Esquemas para Parámetros y Resultados de la API ---
class ItemGenerationParams(BaseModel):
    n_items: int = Field(1, gt=0, le=10, description="Número de ítems a generar.")
    dominio: Dict[str, Any]
    objetivo_aprendizaje: str
    audiencia: Dict[str, Any]
    nivel_cognitivo: str
    formato: FormatoSchema


class GenerationResultSchema(BaseModel):
    message: str
    batch_id: str
    num_items: int


# --- ESQUEMAS INTERNOS UNIFICADOS (Basados en el prompt 01_agent_dominio.md) ---


class DominioSchema(BaseModel):
    area: str
    asignatura: str
    tema: str


class AudienciaSchema(BaseModel):
    nivel_educativo: str
    dificultad_esperada: str

class ContextoSchema(BaseModel):
    contexto_regional: Optional[str] = None
    referencia_curricular: Optional[str] = None


class RecursoGraficoSchema(BaseModel):
    """Define un recurso gráfico que puede acompañar a un estímulo o a una opción."""

    tipo: str = Field(
        ...,
        description="Tipo de recurso. Ej: 'tabla_markdown', 'formula_latex', 'imagen_svg', 'prompt_para_imagen'",
    )
    contenido: str = Field(
        ...,
        description="El 'código fuente' del recurso (texto Markdown, código LaTeX, SVG XML, o un prompt para un modelo de imagen).",
    )
    descripcion_accesible: Optional[str] = Field(
        None, description="Texto alternativo para lectores de pantalla."
    )


class OpcionCuerpoSchema(BaseModel):
    """Se extiende para permitir que una opción de respuesta contenga un gráfico."""

    id: str
    texto: Optional[str] = None  # El texto ahora es opcional
    recurso_grafico: Optional[RecursoGraficoSchema] = None


class CuerpoItemSchema(BaseModel):
    estimulo: Optional[str] = None
    enunciado_pregunta: str
    opciones: List[OpcionCuerpoSchema]
    recurso_grafico: Optional[RecursoGraficoSchema] = None


class RetroalimentacionOpcionSchema(BaseModel):
    id: str
    es_correcta: bool
    justificacion: str


class ClaveDiagnosticoSchema(BaseModel):
    respuesta_correcta_id: str
    errores_comunes_mapeados: List[str]
    retroalimentacion_opciones: List[RetroalimentacionOpcionSchema]


class MetadataCreacionSchema(BaseModel):
    fecha_creacion: str
    agente_generador: str
    version: str = "1.0"


# --- Esquema Principal del Payload del Ítem (UNIFICADO) ---


class ItemPayloadSchema(BaseModel):
    """
    Este es el esquema principal y unificado para el contenido de un ítem.
    TODAS las etapas que lean o escriban el payload deben adherirse a esta estructura.
    """

    item_id: Optional[UUID4] = None
    version: str
    dominio: DominioSchema
    objetivo_aprendizaje: str
    audiencia: AudienciaSchema
    nivel_cognitivo: str
    formato: FormatoSchema
    contexto: Optional[ContextoSchema] = None
    cuerpo_item: CuerpoItemSchema
    clave_y_diagnostico: ClaveDiagnosticoSchema
    metadata_creacion: MetadataCreacionSchema

    # Campos internos para el pipeline, se mantienen.
    revision_log: List[RevisionLogEntry] = Field(default_factory=list)
    final_evaluation: Optional[FinalEvaluationSchema] = None


# --- Esquemas de Soporte (Hallazgos, Correcciones, etc.) ---

class FindingSchema(BaseModel):
    codigo_error: str
    campo_con_error: str
    descripcion_hallazgo: str


class ValidationResultSchema(BaseModel):
    temp_id: str
    status: str
    hallazgos: List[FindingSchema] = Field(default_factory=list)


class CorrectionSchema(BaseModel):
    codigo_error: str
    campo_con_error: str
    descripcion_correccion: str

class RevisionLogEntry(BaseModel):
    """
    Representa una entrada en el historial de auditoría de un ítem.
    """
    timestamp: datetime
    stage_name: str
    status: ItemStatus
    comment: Optional[str] = None

class ScoreBreakdownSchema(BaseModel):
    psychometric_content_score: int
    clarity_pedagogy_score: int
    equity_policy_score: int
    execution_style_score: int

class JustificationSchema(BaseModel):
    """
    Define la justificación de la evaluación final.
    Ahora simplificado para enfocarse únicamente en las áreas de mejora.
    """
    areas_de_mejora: str

class FinalEvaluationSchema(BaseModel):
    """
    El esquema para la evaluación final, ahora usando la
    JustificationSchema simplificada.
    """
    temp_id: str
    is_ready_for_production: bool
    score_total: int
    score_breakdown: ScoreBreakdownSchema
    justification: JustificationSchema

class RefinementResultSchema(BaseModel):
    temp_id: str
    # Ahora se espera que el refinador devuelva el payload con la nueva estructura unificada.
    item_refinado: ItemPayloadSchema
    correcciones_realizadas: List[CorrectionSchema]

class ItemResultSchema(BaseModel):
    """Esquema para el resultado de un solo ítem dentro de un lote."""
    item_id: uuid.UUID
    temp_id: uuid.UUID
    status: str

class BatchStatusResultSchema(BaseModel):
    """Esquema para la respuesta del estado de un lote."""
    batch_id: str
    is_complete: bool
    total_items: int
    processed_items: int
    successful_items: int
    failed_items: int
    results: List[ItemResultSchema]
