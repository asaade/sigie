# app/pipelines/builtins/validate_soft.py

from __future__ import annotations
from difflib import SequenceMatcher
from typing import List
import time

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry
from app.schemas.item_schemas import FindingSchema, ItemPayloadSchema

# Constantes de validación
NEG_WORDS = {"no", "nunca", "jamás", "excepto"}
ABSOL_WORDS = {"siempre", "nunca", "jamás", "todos", "ninguno", "únicamente", "solo"}
FORBIDDEN_OPTIONS = {"todas las anteriores", "ninguna de las anteriores", "a y b son correctas", "b y c son correctas"}
MIN_ACCESSIBILITY_DESC_LENGTH = 15

@register("validate_soft")
class ValidateSoftStage(BaseStage):
    """
    Etapa de validación "suave" que revisa la calidad del estilo y la
    presentación del contenido, añadiendo hallazgos no fatales.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Iniciando etapa de validación suave para {len(items)} ítems.")
        for item in items:
            if item.status == ItemStatus.FATAL:
                continue

            start_time = time.monotonic()
            self._validate_single_item(item)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # El logging final ahora se maneja después de la ejecución, pero
            # add_revision_log_entry ya calcula la duración. Para ser más precisos
            # y consistentes, mantenemos la lógica de logging dentro de _validate_single_item
            # que ya fue actualizada para ser homogénea. El cálculo de tiempo aquí es
            # una buena práctica para futuras métricas a nivel de etapa.

        self.logger.info("Etapa de validación suave completada.")
        return items

    def _validate_single_item(self, item: Item):
        """Realiza una serie de validaciones suaves en un único ítem."""
        if not item.payload:
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "FATAL: El payload del ítem está ausente.")
            return

        payload = item.payload
        initial_findings_count = len(item.findings)

        # Se ejecutan todas las validaciones suaves
        self._check_justification_length(item, payload)
        self._check_option_homogeneity(item, payload)
        self._check_forbidden_options(item, payload)
        self._check_negations_and_absolutes(item, payload)
        self._check_distractor_similarity(item, payload)
        self._check_graphic_accessibility(item, payload)

        # Se registra el resultado final de la etapa de forma homogénea
        if len(item.findings) == initial_findings_count:
            add_revision_log_entry(item, self.stage_name, item.status, "OK. No se encontraron problemas de estilo.")
        else:
            new_findings = item.findings[initial_findings_count:]
            new_codes = [f.codigo_error for f in new_findings]
            comment = f"Se encontraron {len(new_codes)} problema(s) de estilo para guiar al siguiente refinador."
            add_revision_log_entry(item, self.stage_name, item.status, comment, codes_found=new_codes)
            self.logger.warning(f"Item {item.temp_id} con hallazgos de estilo: {new_codes}")

    def _add_finding(self, item: Item, code: str, field: str, description: str):
        """Helper para añadir un hallazgo a la lista del ítem."""
        item.findings.append(FindingSchema(
            codigo_error=code,
            campo_con_error=field,
            descripcion_hallazgo=description
        ))

    def _check_graphic_accessibility(self, item: Item, payload: ItemPayloadSchema):
        """Valida que los recursos gráficos tengan una descripción accesible útil."""
        resources_to_check = []
        if payload.cuerpo_item.recurso_grafico:
            resources_to_check.append((payload.cuerpo_item.recurso_grafico, "cuerpo_item.recurso_grafico"))
        for i, option in enumerate(payload.cuerpo_item.opciones):
            if option.recurso_grafico:
                resources_to_check.append((option.recurso_grafico, f"cuerpo_item.opciones[{i}].recurso_grafico"))

        for resource, path in resources_to_check:
            if not resource.descripcion_accesible or len(resource.descripcion_accesible) < MIN_ACCESSIBILITY_DESC_LENGTH:
                self._add_finding(item, "E130_FALLA_ACCESIBILIDAD", f"{path}.descripcion_accesible", "La descripción accesible es demasiado corta o ausente.")

    def _check_justification_length(self, item: Item, payload: ItemPayloadSchema):
        """Valida que las justificaciones no sean excesivamente cortas."""
        for i, retro in enumerate(payload.clave_y_diagnostico.retroalimentacion_opciones):
            if len(retro.justificacion.split()) < 5:
                self._add_finding(item, "S002_JUSTIFICACION_BREVE", f"clave_y_diagnostico.retroalimentacion_opciones[{i}].justificacion", "La justificación contiene menos de 5 palabras.")

    def _check_option_homogeneity(self, item: Item, payload: ItemPayloadSchema):
        """Valida que las opciones tengan una longitud relativamente similar."""
        options = payload.cuerpo_item.opciones
        if not options: return

        texts = [opt.texto for opt in options if opt.texto]
        if len(texts) < 2: return

        word_counts = [len(text.split()) for text in texts]
        min_len, max_len = min(word_counts), max(word_counts)
        if min_len > 0 and (max_len / min_len) >= 3.0:
            self._add_finding(item, "E104_OPCIONES_NO_HOMOGENEAS", "cuerpo_item.opciones", "La longitud de las opciones varía significativamente (una es 3 veces más larga que otra).")

    def _check_forbidden_options(self, item: Item, payload: ItemPayloadSchema):
        """Valida que no se usen tipos de opción prohibidos."""
        for i, opt in enumerate(payload.cuerpo_item.opciones):
            if opt.texto and opt.texto.lower().strip() in FORBIDDEN_OPTIONS:
                self._add_finding(item, "E106_TIPO_OPCION_PROHIBIDO", f"cuerpo_item.opciones[{i}].texto", "Se utilizó un tipo de opción prohibido (ej. 'todas las anteriores').")

    def _check_negations_and_absolutes(self, item: Item, payload: ItemPayloadSchema):
        """Valida el uso de negaciones y absolutos en el enunciado."""
        stem_lower = f" {payload.cuerpo_item.enunciado_pregunta.lower()} "
        if any(f" {word} " in stem_lower for word in NEG_WORDS):
            self._add_finding(item, "E101_NEGACION_MINUSCULA", "cuerpo_item.enunciado_pregunta", "Se encontró una palabra de negación en minúsculas en el enunciado.")
        if any(f" {word} " in stem_lower for word in ABSOL_WORDS):
            self._add_finding(item, "E102_USO_DE_ABSOLUTOS", "cuerpo_item.enunciado_pregunta", "Se encontró una palabra absoluta en el enunciado.")

    def _check_distractor_similarity(self, item: Item, payload: ItemPayloadSchema):
        """Valida que los distractores no sean demasiado similares entre sí."""
        options = payload.cuerpo_item.opciones
        correct_id = payload.clave_y_diagnostico.respuesta_correcta_id
        distractors = [opt.texto for opt in options if opt.id != correct_id and opt.texto]

        if len(distractors) < 2: return

        for i in range(len(distractors)):
            for j in range(i + 1, len(distractors)):
                ratio = SequenceMatcher(None, distractors[i].lower(), distractors[j].lower()).ratio()
                if ratio > 0.9:
                    self._add_finding(item, "E112_DISTRACTORES_SIMILARES", "cuerpo_item.opciones", "Dos o más distractores son textualmente muy similares (ratio > 0.9).")
                    return
