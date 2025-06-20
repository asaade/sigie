# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import json
import logging
from typing import List, Dict, Any

from ..registry import register
from ._helpers import add_tokens
from app.schemas.models import Item
from app.llm import generate_response, LLMResponse
from app.prompts import load_prompt
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams, AuditEntrySchema, ReportEntrySchema
from pydantic import ValidationError
from ..utils.parsers import extract_json_block

logger = logging.getLogger(__name__)

@register("generate")
async def generate_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Genera el payload de los ítems en un solo lote utilizando un LLM.
    Asigna los resultados a los objetos Item existentes en la lista de entrada.
    """
    # Se asume que 'items' es una lista de objetos Item pre-inicializados,
    # posiblemente con solo el temp_id y el payload vacío o parcial,
    # y que 'user_params' contiene los parámetros de generación para el lote completo.

    params = ctx.get("params", {}).get("generate", {})
    user_params: UserGenerateParams = UserGenerateParams.model_validate(ctx.get("user_params", {}))

    prompt_name = params.get("prompt", "agent_dominio.md")

    try:
        prompt_tpl = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found: {e}",
                    severity="error"
                )
            )
        logger.error(f"Failed to load prompt '{prompt_name}': {e}")
        return items

    total_tokens_used_in_stage = 0
    stage_name = "generate" # Nombre de la etapa para auditoría

    # Preparamos el input para la ÚNICA llamada al LLM para este lote
    # Aseguramos que cada ítem en el lote tenga un item_id (UUID) para que el LLM lo use si es necesario
    # Aunque el prompt actual del agente de dominio no usa `item_id` en la entrada esperada,
    # es buena práctica incluirlo si el output lo requiere o si en el futuro se necesita mapeo.
    items_for_llm_input = []
    for item in items:
        # Aquí puedes construir un "seed" o "request" por ítem si el LLM necesita especificidad
        # Para el agente de dominio actual, los user_params son globales.
        # El item_id es crucial para que el LLM lo incluya en su respuesta y mapear.
        items_for_llm_input.append({"item_id": str(item.temp_id)}) # Usamos temp_id como item_id inicial

    user_input_for_llm = {
        "tipo_generacion": user_params.tipo_generacion.value if user_params.tipo_generacion else "item",
        "cantidad": len(items), # Esto es crucial para el prompt
        "idioma_item": user_params.idioma_item,
        "area": user_params.area,
        "asignatura": user_params.asignatura,
        "tema": user_params.tema,
        "nivel_destinatario": user_params.nivel_destinatario,
        "nivel_cognitivo": user_params.nivel_cognitivo,
        "dificultad_prevista": user_params.dificultad_prevista,
        "tipo_reactivo": user_params.tipo_reactivo.value if user_params.tipo_reactivo else None,
        "fragmento_contexto": user_params.fragmento_contexto,
        "recurso_visual": user_params.recurso_visual.model_dump() if user_params.recurso_visual else None,
        "estimulo_compartido": user_params.estimulo_compartido,
        # Si 'especificaciones_por_item' es un campo de user_params y el prompt lo usa:
        "especificaciones_por_item": [spec.model_dump() for spec in user_params.especificaciones_por_item] if user_params.especificaciones_por_item else None,
    }

    messages = [
        {"role": "system", "content": prompt_tpl.format(n_items=len(items))}, # Pasar n_items al prompt system
        {"role": "user", "content": json.dumps(user_input_for_llm, ensure_ascii=False)},
    ]

    logger.info(f"Generating {len(items)} items with prompt '{prompt_name}' in a single batch.")

    # ÚNICA Llamada al LLM
    resp: LLMResponse = await generate_response(messages)

    total_tokens_used_in_stage = resp.usage.get("total", 0)
    add_tokens(ctx, total_tokens_used_in_stage)

    # Procesar la respuesta que debe ser un ARRAY de JSONs de ItemPayloadSchema
    clean_json_str = extract_json_block(resp.text)

    generated_payloads: List[ItemPayloadSchema] = []
    try:
        raw_llm_response = json.loads(clean_json_str)

        # El LLM puede devolver directamente el array, o un objeto con una clave "items"
        if isinstance(raw_llm_response, dict) and "items" in raw_llm_response:
            payloads_data = raw_llm_response["items"]
        elif isinstance(raw_llm_response, list):
            payloads_data = raw_llm_response
        else:
            raise ValueError("LLM response is not a list or an object containing an 'items' key.")

        generated_payloads = [ItemPayloadSchema.model_validate(p) for p in payloads_data]

        if len(generated_payloads) != len(items):
            raise ValueError(f"Expected {len(items)} items but LLM generated {len(generated_payloads)}. Response: {clean_json_str[:500]}...")

        # Mapear los payloads generados a los objetos Item originales
        # Asumimos que el LLM mantiene el item_id (temp_id) en el payload generado
        payloads_by_id = {payload.item_id: payload for payload in generated_payloads}

        for item in items:
            generated_payload = payloads_by_id.get(item.temp_id)
            if generated_payload:
                item.payload = generated_payload
                item.status = "generated" # Nuevo estado para indicar generación exitosa
                item.prompt_v = prompt_name
                # Distribuir los tokens equitativamente o dejarlos como total para la etapa
                # Aquí lo distribuimos por ítem, pero ctx['usage_tokens_total'] tendrá el total.
                item.token_usage = total_tokens_used_in_stage // len(items)

                # ¡Añadir entrada de auditoría!
                item.audits.append(
                    AuditEntrySchema(
                        stage=stage_name,
                        summary=f"Ítem generado exitosamente por el Agente de Dominio (prompt: {prompt_name})."
                    )
                )
            else:
                item.status = "generation_failed"
                item.errors.append(
                    ReportEntrySchema(
                        code="ITEM_ID_MISMATCH",
                        message=f"LLM did not return a payload for item_id: {item.temp_id}",
                        severity="error"
                    )
                )
                item.audits.append(
                    AuditEntrySchema(
                        stage=stage_name,
                        summary=f"Fallo al mapear el payload generado por el LLM al item (missing item_id: {item.temp_id})."
                    )
                )


        logger.info(f"Successfully generated and validated {len(items)} items from LLM batch response.")

    except (ValidationError, json.JSONDecodeError, ValueError) as err:
        # Si falla el parseo, la validación de la lista, o la cantidad de ítems
        error_msg = f"Failed to parse/validate LLM batch response or incorrect item count: {err}. Raw LLM response: {resp.text[:1000]}..."
        logger.error(f"Batch generation failed: {error_msg}")

        for item in items:
            if item.status == "pending": # Solo actualizar los que no han sido marcados ok
                item.status = "generation_failed" # Considerar fatal para todos los ítems del lote si la respuesta es inválida
                item.errors.append(
                    ReportEntrySchema(
                        code="BATCH_GENERATION_ERROR",
                        message=error_msg,
                        field="payload",
                        severity="error"
                    )
                )
                item.audits.append(
                    AuditEntrySchema(
                        stage=stage_name,
                        summary=f"Error fatal durante la generación en lote. Detalles: {error_msg[:200]}..."
                    )
                )

    return items
