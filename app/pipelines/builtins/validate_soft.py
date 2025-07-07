# app/pipelines/builtins/validate_soft.py

from __future__ import annotations
from difflib import SequenceMatcher
from typing import List

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry
from app.schemas.item_schemas import FindingSchema

# Constantes de validación
NEG_WORDS = {"no", "nunca", "jamás"}
ABSOL_WORDS = {"siempre", "nunca", "jamás", "todos", "ninguno"}
FORBIDDEN_OPTIONS = {"todas las anteriores", "ninguna de las anteriores"}
MIN_ACCESSIBILITY_DESC_LENGTH = 15

@register("validate_soft")
class ValidateSoftStage(BaseStage):
    """
    Etapa de validación "suave" que revisa la calidad del contenido,
    incluyendo la accesibilidad de los recursos gráficos.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Iniciando etapa de validación suave para {len(items)} ítems.")
        for item in items:
            if item.status == ItemStatus.FATAL:
                continue
            self._validate_single_item(item)
        self.logger.info("Etapa de validación suave completada.")
        return items

    def _validate_single_item(self, item: Item):
        """Realiza una serie de validaciones suaves en un único ítem."""
        if not item.payload:
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "El payload del ítem está ausente.")
            return

        initial_findings_count = len(item.findings)

        self._check_justification_length(item)
        self._check_stimulus_vs_stem(item)
        self._check_option_homogeneity(item)
        self._check_forbidden_options(item)
        self._check_negations_and_absolutes(item)
        self._check_distractor_similarity(item)
        self._check_graphic_accessibility(item) # <-- NUEVA VALIDACIÓN

        if len(item.findings) == initial_findings_count:
            add_revision_log_entry(item, self.stage_name, item.status, "Soft validation passed.")
        else:
            new_findings_codes = [f.codigo_error for f in item.findings[initial_findings_count:]]
            comment = f"Soft validation found issues: {', '.join(new_findings_codes)}"
            add_revision_log_entry(item, self.stage_name, item.status, comment)
            self.logger.warning(f"Item {item.temp_id} found issues in soft validation: {new_findings_codes}")

    def _add_finding(self, item: Item, code: str, field: str = "N/A"):
        """Helper para añadir un hallazgo a la lista del ítem."""
        item.findings.append(FindingSchema(
            codigo_error=code,
            campo_con_error=field,
            descripcion_hallazgo=f"Soft validation failed for code {code}."
        ))

    def _check_graphic_accessibility(self, item: Item):
        """NUEVO: Valida que los recursos gráficos tengan una descripción accesible útil."""
        resources_to_check = []
        if item.payload.cuerpo_item.recurso_grafico:
            resources_to_check.append((item.payload.cuerpo_item.recurso_grafico, "cuerpo_item.recurso_grafico"))
        for i, option in enumerate(item.payload.cuerpo_item.opciones):
            if option.recurso_grafico:
                resources_to_check.append((option.recurso_grafico, f"cuerpo_item.opciones[{i}].recurso_grafico"))

        for resource, path in resources_to_check:
            if not resource.descripcion_accesible or len(resource.descripcion_accesible) < MIN_ACCESSIBILITY_DESC_LENGTH:
                self._add_finding(item, "W125_DESCRIPCION_DEFICIENTE", f"{path}.descripcion_accesible")

    # --- El resto de los métodos de validación suave se mantienen igual ---

    def _check_justification_length(self, item: Item):
        for retro in item.payload.clave_y_diagnostico.retroalimentacion_opciones:
            if len(retro.justificacion) < 20:
                code = "S001" if retro.es_correcta else "S002"
                self._add_finding(item, code, f"clave_y_diagnostico.retroalimentacion_opciones.{retro.id}")

    def _check_stimulus_vs_stem(self, item: Item):
        if item.payload.cuerpo_item.estimulo and item.payload.cuerpo_item.estimulo == item.payload.cuerpo_item.enunciado_pregunta:
            self._add_finding(item, "S003", "cuerpo_item.estimulo")

    def _check_option_homogeneity(self, item: Item):
        options = item.payload.cuerpo_item.opciones
        if not options: return

        texts = [opt.texto for opt in options if opt.texto]
        if not texts: return

        word_counts = [len(text.split()) for text in texts]
        valid_lengths = [count for count in word_counts if count > 0]
        if not valid_lengths: return

        min_len, max_len = min(valid_lengths), max(valid_lengths)
        if min_len > 0 and (max_len / min_len) >= 2.5:
            self._add_finding(item, "W104_OPT_LEN_VAR", "cuerpo_item.opciones")

    def _check_forbidden_options(self, item: Item):
        for opt in item.payload.cuerpo_item.opciones:
            if opt.texto and opt.texto.lower().strip() in FORBIDDEN_OPTIONS:
                self._add_finding(item, "E106_COMPLEX_OPTION_TYPE", f"cuerpo_item.opciones.{opt.id}")

    def _check_negations_and_absolutes(self, item: Item):
        stem_lower = item.payload.cuerpo_item.enunciado_pregunta.lower()
        if any(f" {word} " in stem_lower for word in NEG_WORDS):
            self._add_finding(item, "W101_STEM_NEG_LOWER", "cuerpo_item.enunciado_pregunta")
        if any(f" {word} " in stem_lower for word in ABSOL_WORDS):
            self._add_finding(item, "W102_ABSOL_STEM", "cuerpo_item.enunciado_pregunta")

    def _check_distractor_similarity(self, item: Item):
        options = item.payload.cuerpo_item.opciones
        correct_id = item.payload.clave_y_diagnostico.respuesta_correcta_id
        distractors = [opt.texto for opt in options if opt.id != correct_id and opt.texto]

        if len(distractors) < 2: return

        similarity_scores = []
        for i in range(len(distractors)):
            for j in range(i + 1, len(distractors)):
                ratio = SequenceMatcher(None, distractors[i].lower(), distractors[j].lower()).ratio()
                similarity_scores.append(ratio)

        if similarity_scores and (sum(similarity_scores) / len(similarity_scores)) > 0.85:
            self._add_finding(item, "W112_DISTRACTOR_SIMILAR", "cuerpo_item.opciones")
