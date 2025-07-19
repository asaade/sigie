# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import re
from typing import List

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemPayloadSchema, RecursoGraficoSchema, FindingSchema
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry

@register("validate_hard")
class ValidateHardStage(BaseStage):
    """
    Etapa de validación "dura" que realiza comprobaciones programáticas
    sobre la consistencia interna y estructural del payload del ítem.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Iniciando validación dura para {len(items)} ítems.")
        for item in items:
            if item.status == ItemStatus.FATAL:
                continue

            # El método de validación ahora solo devuelve True/False.
            is_valid = self._validate_single_item(item)

            # El logging de éxito se realiza solo si no se encontraron errores fatales.
            if is_valid:
                add_revision_log_entry(
                    item, self.stage_name, item.status, "OK. Las validaciones estructurales pasaron."
                )
        self.logger.info("Validación dura completada.")
        return items

    def _validate_single_item(self, item: Item) -> bool:
        """
        Realiza una serie de validaciones. Devuelve True si todo está bien,
        y False si alguna validación falla.
        """
        if not item.payload:
            self._add_fatal_finding(item, "E952_PAYLOAD_AUSENTE", "N/A", "El payload del ítem está ausente.")
            return False

        payload = item.payload

        if not self._validate_required_text_fields(item, payload): return False
        if not self._validate_options_and_key(item, payload): return False
        if not self._validate_unique_option_content(item, payload): return False
        if not self._validate_completamiento(item, payload): return False
        if not self._validate_ordenamiento(item, payload): return False
        if not self._validate_graphic_resources(item, payload): return False

        return True

    def _add_finding(self, item: Item, code: str, field: str, description: str):
        """Helper para añadir un hallazgo a la lista del ítem."""
        item.findings.append(FindingSchema(
            codigo_error=code,
            campo_con_error=field,
            descripcion_hallazgo=description
        ))

    def _add_fatal_finding(self, item: Item, code: str, field: str, message: str):
        """Helper centralizado para registrar errores fatales."""
        # CORRECCIÓN: Ahora también añade un "finding" estructurado.
        self._add_finding(item, code, field, f"FATAL: {message}")
        add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, f"FATAL: {message}", codes_found=[code])

    def _validate_required_text_fields(self, item: Item, payload: ItemPayloadSchema) -> bool:
        if not payload.cuerpo_item.enunciado_pregunta or not payload.cuerpo_item.enunciado_pregunta.strip():
            self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", "cuerpo_item.enunciado_pregunta", "El campo 'enunciado_pregunta' no puede estar vacío.")
            return False
        for i, opt in enumerate(payload.cuerpo_item.opciones):
            if not opt.texto or not opt.texto.strip():
                self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", f"cuerpo_item.opciones[{i}].texto", f"El texto de la opción '{opt.id}' no puede estar vacío.")
                return False
        return True

    def _validate_options_and_key(self, item: Item, payload: ItemPayloadSchema) -> bool:
        option_ids = {opt.id for opt in payload.cuerpo_item.opciones}
        if len(option_ids) != len(payload.cuerpo_item.opciones):
            self._add_fatal_finding(item, "E011_ID_OPCION_DUPLICADO", "cuerpo_item.opciones", "Se encontraron IDs de opción duplicados.")
            return False

        correct_option_id = payload.clave_y_diagnostico.respuesta_correcta_id
        if correct_option_id not in option_ids:
            self._add_fatal_finding(item, "E013_ID_CLAVE_NO_COINCIDE", "clave_y_diagnostico.respuesta_correcta_id", f"La respuesta correcta declarada ('{correct_option_id}') no existe en las opciones.")
            return False

        correct_flags = [retro.es_correcta for retro in payload.clave_y_diagnostico.retroalimentacion_opciones if retro.es_correcta]
        if len(correct_flags) != 1:
            self._add_fatal_finding(item, "E012_CONTEO_CLAVE_INCORRECTO", "clave_y_diagnostico.retroalimentacion_opciones", f"Se encontraron {len(correct_flags)} opciones marcadas como correctas, se esperaba 1.")
            return False

        return True

    def _validate_unique_option_content(self, item: Item, payload: ItemPayloadSchema) -> bool:
        option_texts = [opt.texto.strip() for opt in payload.cuerpo_item.opciones if opt.texto]
        if len(option_texts) != len(set(option_texts)):
            self._add_fatal_finding(item, "E014_OPCION_DUPLICADA", "cuerpo_item.opciones", "Se encontraron dos o más opciones con el mismo texto.")
            return False
        return True

    def _validate_completamiento(self, item: Item, payload: ItemPayloadSchema) -> bool:
        if payload.formato.tipo_reactivo == "completamiento":
            holes = payload.cuerpo_item.enunciado_pregunta.count("___")
            if holes > 0:
                if payload.cuerpo_item.estimulo and "___" in payload.cuerpo_item.estimulo:
                    self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", "cuerpo_item.estimulo", "Los huecos de completamiento ('___') solo deben aparecer en 'enunciado_pregunta'.")
                    return False
                for i, opt in enumerate(payload.cuerpo_item.opciones):
                    segments = opt.texto.split(' | ')
                    if len(segments) != holes:
                        self._add_fatal_finding(item, "E030_COMPLETAMIENTO_INCONSISTENTE", f"cuerpo_item.opciones[{i}].texto", f"El número de segmentos ({len(segments)}) en la opción '{opt.id}' no coincide con los huecos ({holes}).")
                        return False
        return True

    def _validate_ordenamiento(self, item: Item, payload: ItemPayloadSchema) -> bool:
        if payload.formato.tipo_reactivo == "ordenamiento":
            if not payload.cuerpo_item.estimulo:
                self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", "cuerpo_item.stimulo", "Ítems de ordenamiento requieren un estímulo con la lista de elementos.")
                return False
            elements = re.findall(r"^\s*\d+\.", payload.cuerpo_item.estimulo, re.MULTILINE)
            if not elements:
                self._add_fatal_finding(item, "E031_ORDENAMIENTO_INCONSISTENTE", "cuerpo_item.stimulo", "El estímulo para el ítem de ordenamiento no contiene una lista numerada.")
                return False

            n_elements = len(elements)
            expected_nums = set(range(1, n_elements + 1))

            for i, opt in enumerate(payload.cuerpo_item.opciones):
                try:
                    nums = {int(n.strip()) for n in opt.texto.split(',')}
                    if nums != expected_nums:
                        self._add_fatal_finding(item, "E031_ORDENAMIENTO_INCONSISTENTE", f"cuerpo_item.opciones[{i}].texto", f"La opción '{opt.id}' no es una permutación válida de los {n_elements} elementos.")
                        return False
                except (ValueError, AttributeError):
                    self._add_fatal_finding(item, "E031_ORDENAMIENTO_INCONSISTENTE", f"cuerpo_item.opciones[{i}].texto", f"La opción '{opt.id}' ('{opt.texto}') no tiene un formato de permutación válido.")
                    return False
        return True

    def _validate_graphic_resources(self, item: Item, payload: ItemPayloadSchema) -> bool:
        resources_to_check = []
        if payload.cuerpo_item.recurso_grafico:
            resources_to_check.append((payload.cuerpo_item.recurso_grafico, "cuerpo_item.recurso_grafico"))
        for i, option in enumerate(payload.cuerpo_item.opciones):
            if option.recurso_grafico:
                resources_to_check.append((option.recurso_grafico, f"cuerpo_item.opciones[{i}].recurso_grafico"))

        for resource, path in resources_to_check:
            if not isinstance(resource, RecursoGraficoSchema): continue
            if not resource.tipo or not isinstance(resource.tipo, str):
                self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", path, "Recurso gráfico con campo 'tipo' ausente o inválido.")
                return False
            if not resource.contenido or not isinstance(resource.contenido, str):
                self._add_fatal_finding(item, "E001_SCHEMA_INVALIDO", path, "Recurso gráfico con campo 'contenido' ausente o inválido.")
                return False
        return True
