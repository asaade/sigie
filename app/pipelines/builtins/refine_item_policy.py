# app/pipelines/builtins/refine_item_policy.py

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.pipelines.refiner_stage import BaseRefinerStage
import json

@register("refine_item_policy")
class RefineItemPolicyStage(BaseRefinerStage):
    """
    Etapa que refina las POLÍTICAS de un ítem usando el Maestro de Equidad
    y el sistema de parches estructurados.
    """
    success_status = ItemStatus.POLICY_REFINEMENT_SUCCESS
    stage_name_in_log = "Refinamiento de Políticas"
    input_key = "item_a_refinar"

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Implementación para el Maestro de Equidad.
        Extrae solo los textos de cara al público para buscar sesgos.
        """
        if not item.payload:
            return json.dumps({"error": "No se puede preparar el input sin un payload."})

        payload = item.payload

        # Recolectar solo los textos necesarios para el análisis de políticas.
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

        if payload.cuerpo_item.recurso_grafico and payload.cuerpo_item.recurso_grafico.descripcion_accesible:
             campos_a_revisar.append({
                "path": "cuerpo_item.recurso_grafico.descripcion_accesible",
                "texto_original": payload.cuerpo_item.recurso_grafico.descripcion_accesible
            })

        # Construir el payload final para el LLM.
        input_data = {
            "temp_id": str(item.temp_id),
            "campos_a_revisar": campos_a_revisar
        }

        return json.dumps(input_data, ensure_ascii=False)
