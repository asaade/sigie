# app/schemas/enums.py

from enum import Enum

class ItemStatus(str, Enum):
    """
    Define los estados posibles y granulares que un ítem puede tener a lo largo del pipeline.
    """
    GENERATION_SUCCESS = "generation_success"
    PENDING = "pending"
    REQUEST_VALIDATION_SUCCESS = "request_success"

    # Estados de Validación (Detectan, no corrigen)
    CONTENT_POLISHING_SUCCESS = "content_refinement_success"
    # LOGIC_VALIDATION_NEEDS_REVISION = "logic_validation_needs_revision"
    # LOGIC_VALIDATION_SUCCESS = "logic_validation_success"
    # POLICY_VALIDATION_NEEDS_REVISION = "policy_validation_needs_revision"
    # POLICY_VALIDATION_SUCCESS = "policy_validation_success"

    # Estados de Refinamiento (NUEVA ESTRUCTURA DE 3 PILARES)
    PSYCHOMETRIC_REFINEMENT_SUCCESS = "psychometric_refinement_success" # Para el Maestro Psicométrico
    POLICY_REFINEMENT_SUCCESS = "policy_refinement_success"           # Para el Maestro de Equidad
    STYLE_REFINEMENT_SUCCESS = "style_refinement_success"             # Para el Editor de Estilo

    # Estados Finales
    EVALUATION_COMPLETE = "evaluation_complete"
    PERSISTENCE_SUCCESS = "persistence_success"

    # Estados de Fallo o Excepción
    FATAL = "fatal"
    NEEDS_REVISION = "needs_revision"
    REJECTED_UNFIXABLE = "rejected_unfixable"
    SKIPPED = "skipped"
