# app/pipelines/builtins/refine_item_style.py

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.pipelines.refiner_stage import BaseRefinerStage
import json

@register("refine_item_style")
class RefineItemStyleStage(BaseRefinerStage):
    """
    Etapa que refina el ESTILO del ítem usando el Editor de Estilo
    y el sistema de parches estructurados.
    """
    success_status = ItemStatus.STYLE_REFINEMENT_SUCCESS
    stage_name_in_log = "Refinamiento de Estilo"
    input_key = "item_a_refinar"

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Implementación específica para el Editor de Estilo.
        Recolecta todos los campos de texto del ítem que son visibles
        para el usuario final y los hallazgos de la validación suave.
        """
        if not item.payload:
            return json.dumps({"error": "No se puede preparar el input sin un payload."})

        payload = item.payload

        # 1. Recolectar todos los textos que el editor necesita revisar.
        campos_a_revisar = []

        if payload.cuerpo_item.estimulo:
            campos_a_revisar.append({
                "path": "cuerpo_item.estimulo",
                "texto_original": payload.cuerpo_item.estimulo
            })

        campos_a_revisar.append({
            "path": "cuerpo_item.enunciado_pregunta",
            "texto_original": payload.cuerpo_item.enunciado_pregunta
        })

        for i, opcion in enumerate(payload.cuerpo_item.opciones):
            if opcion.texto:
                campos_a_revisar.append({
                    "path": f"cuerpo_item.opciones[{i}].texto",
                    "texto_original": opcion.texto
                })

        for i, retro in enumerate(payload.clave_y_diagnostico.retroalimentacion_opciones):
             campos_a_revisar.append({
                "path": f"clave_y_diagnostico.retroalimentacion_opciones[{i}].justificacion",
                "texto_original": retro.justificacion
            })

        if payload.cuerpo_item.recurso_grafico and payload.cuerpo_item.recurso_grafico.descripcion_accesible:
            campos_a_revisar.append({
                "path": "cuerpo_item.recurso_grafico.descripcion_accesible",
                "texto_original": payload.cuerpo_item.recurso_grafico.descripcion_accesible
            })

        # 2. Construir el payload final para el LLM.
        input_data = {
            "temp_id": str(item.temp_id),
            "campos_a_revisar": campos_a_revisar
        }

        # 3. Añadir hallazgos del validador suave como guía.
        if item.findings:
            input_data["hallazgos_guia"] = [f.model_dump(mode="json") for f in item.findings]

        return json.dumps(input_data, ensure_ascii=False)
