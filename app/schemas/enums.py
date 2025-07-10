# app/schemas/enums.py

from enum import Enum

class ItemStatus(str, Enum):
    """
    Define los estados posibles y granulares que un ítem puede tener a lo largo del pipeline.
    Al estar en su propio archivo, rompe las dependencias circulares.
    """
    PENDING = "pending"
    REQUEST_VALIDATION_SUCCESS = "request_success"
    GENERATION_SUCCESS = "generation_success"
    LOGIC_VALIDATION_SUCCESS = "logic_validation_success"
    LOGIC_VALIDATION_NEEDS_REVISION = "logic_validation_needs_revision"
    LOGIC_REFINEMENT_SUCCESS = "logic_refinement_success"
    CONTENT_VALIDATION_SUCCESS = "content_validation_success"
    CONTENT_VALIDATION_NEEDS_REVISION = "content_validation_needs_revision"
    CONTENT_REFINEMENT_SUCCESS = "content_refinement_success"
    POLICY_VALIDATION_SUCCESS = "policy_validation_success"
    POLICY_VALIDATION_NEEDS_REVISION = "policy_validation_needs_revision"
    POLICY_REFINEMENT_SUCCESS = "policy_refinement_success"
    STYLE_REFINEMENT_SUCCESS = "style_refinement_success"
    EVALUATION_COMPLETE = "evaluation_complete"
    PERSISTENCE_SUCCESS = "persistence_success"
    SKIPPED = "skipped"
    FATAL = "fatal"
