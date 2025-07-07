# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import re
from typing import List

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemPayloadSchema, RecursoGraficoSchema
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry

@register("validate_hard")
class ValidateHardStage(BaseStage):
    """
    Etapa de validación "dura" que realiza comprobaciones programáticas
    sobre la consistencia interna del payload del ítem, incluyendo la
    estructura de los recursos gráficos.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Starting hard validation for {len(items)} items.")
        for item in items:
            if item.status == ItemStatus.FATAL:
                continue
            self._validate_single_item(item)
        self.logger.info(f"Hard validation completed for {len(items)} items.")
        return items

    def _validate_single_item(self, item: Item):
        """
        Realiza una serie de validaciones en un único ítem.
        Si alguna validación falla, se establece el estado como FATAL.
        """
        if not item.payload or not isinstance(item.payload, ItemPayloadSchema):
            add_revision_log_entry(
                item, self.stage_name, ItemStatus.FATAL,
                "El payload del ítem está ausente o tiene un tipo incorrecto."
            )
            return

        # --- Se ejecutan las validaciones en secuencia ---
        # Si una validación retorna False, significa que ha fallado y ha puesto
        # el estado en FATAL, por lo que detenemos la validación para este ítem.
        if not self._validate_options_and_key(item): return
        if not self._validate_completamiento(item): return
        if not self._validate_graphic_resources(item): return

        # Si todas las validaciones pasan, se registra el éxito.
        add_revision_log_entry(
            item, self.stage_name, item.status, "Hard validation passed successfully."
        )
        self.logger.info(f"Item {item.temp_id} passed hard validation.")

    def _validate_options_and_key(self, item: Item) -> bool:
        """Valida la consistencia entre opciones, clave de respuesta y retroalimentación."""
        payload = item.payload
        cuerpo_item = payload.cuerpo_item
        clave_diagnostico = payload.clave_y_diagnostico
        option_ids = {opt.id for opt in cuerpo_item.opciones}

        if len(option_ids) != len(cuerpo_item.opciones):
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "Se encontraron IDs de opción duplicados.")
            return False

        correct_option_id = clave_diagnostico.respuesta_correcta_id
        if correct_option_id not in option_ids:
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, f"La respuesta correcta ('{correct_option_id}') no existe.")
            return False

        retro_ids = {retro.id for retro in clave_diagnostico.retroalimentacion_opciones}
        if option_ids != retro_ids:
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "Los IDs en retroalimentación no coinciden con las opciones.")
            return False

        correct_flags = [retro.es_correcta for retro in clave_diagnostico.retroalimentacion_opciones if retro.es_correcta]
        if len(correct_flags) != 1:
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, f"Se encontraron {len(correct_flags)} opciones marcadas como correctas, se esperaba 1.")
            return False

        correct_retro_option = next((retro for retro in clave_diagnostico.retroalimentacion_opciones if retro.es_correcta), None)
        if not correct_retro_option or correct_retro_option.id != correct_option_id:
             add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "Inconsistencia entre 'es_correcta=true' y 'respuesta_correcta_id'.")
             return False

        return True

    def _validate_completamiento(self, item: Item) -> bool:
        """Valida la consistencia para ítems de tipo 'completamiento'."""
        if item.payload.formato.tipo_reactivo == "completamiento":
            holes = item.payload.cuerpo_item.enunciado_pregunta.count("___")
            if holes > 0:
                for opt in item.payload.cuerpo_item.opciones:
                    segs = re.split(r'\s*,\s*|\s+y\s+', opt.texto)
                    if len(segs) != holes:
                        add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, f"Para 'completamiento', los segmentos en la opción '{opt.id}' no coinciden con los huecos.")
                        return False
        return True

    def _validate_graphic_resources(self, item: Item) -> bool:
        """NUEVO: Valida la estructura básica de todos los recursos gráficos en el ítem."""
        # Recolectar todos los recursos gráficos del ítem
        resources_to_check = []
        if item.payload.cuerpo_item.recurso_grafico:
            resources_to_check.append(item.payload.cuerpo_item.recurso_grafico)
        for option in item.payload.cuerpo_item.opciones:
            if option.recurso_grafico:
                resources_to_check.append(option.recurso_grafico)

        for resource in resources_to_check:
            if not isinstance(resource, RecursoGraficoSchema):
                continue # Ya fallará en la validación Pydantic general

            if not resource.tipo or not isinstance(resource.tipo, str):
                add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "Recurso gráfico con campo 'tipo' ausente o inválido.")
                return False

            if not resource.contenido or not isinstance(resource.contenido, str):
                add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, "Recurso gráfico con campo 'contenido' ausente o inválido.")
                return False

        return True
