# schemas_gui.py

from pydantic import BaseModel
from typing import List, Optional, Literal

# --- Modelos de Datos Pydantic para la GUI ---

class Dominio(BaseModel):
    area: str
    asignatura: str
    tema: str

class RecursoGrafico(BaseModel):
    formato: Literal["tabla_markdown", "formula_latex", "prompt_para_imagen"]
    contenido: str
    descripcion_accesible: str

class Opcion(BaseModel):
    id: str
    texto: str

class CuerpoItem(BaseModel):
    estimulo: Optional[str] = None
    recurso_grafico: Optional[RecursoGrafico] = None
    enunciado_pregunta: str
    opciones: List[Opcion]

class RetroalimentacionOpcion(BaseModel):
    id: str
    es_correcta: bool
    justificacion: str

class ClaveYDiagnostico(BaseModel):
    respuesta_correcta_id: str
    retroalimentacion_opciones: List[RetroalimentacionOpcion]

class FinalEvaluationJustification(BaseModel):
    areas_de_mejora: str

class FinalEvaluation(BaseModel):
    score_total: int
    justification: FinalEvaluationJustification

class Reactivo(BaseModel):
    temp_id: str
    dominio: Dominio
    objetivo_aprendizaje: str
    # (CAMBIO) Se añade el campo nivel_cognitivo para que coincida con el schema principal
    nivel_cognitivo: str
    cuerpo_item: CuerpoItem
    clave_y_diagnostico: ClaveYDiagnostico
    final_evaluation: FinalEvaluation
