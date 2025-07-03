# app/core/error_metadata.py
from typing import Dict, Any

_ERROR_CATALOG_FLAT: Dict[str, Dict[str, Any]] = {
    # ESTILO
    "E020_STEM_LENGTH": {"message": "Enunciado excede el límite de longitud.", "fix_hint": "Recortar el enunciado sin perder claridad.", "severity": "error"},
    "E040_OPTION_LENGTH": {"message": "Longitud de opciones desbalanceada o demasiado extensa.", "fix_hint": "Igualar o acortar el texto de las opciones según corresponda.", "severity": "error", "details_allowed": ["excess", "variation"]},
    "E080_MATH_FORMAT": {"message": "Mezcla de Unicode y LaTeX o formato matemático inconsistente.", "fix_hint": "Usar un solo sistema de notación de forma consistente.", "severity": "error"},
    "E091_CORRECTA_SIMILAR_STEM": {"message": "Opción correcta demasiado similar al enunciado; revela la respuesta.", "fix_hint": "Reformular enunciado u opción para evitar pistas obvias.", "severity": "error"},
    "E106_COMPLEX_OPTION_TYPE": {"message": "Se usó “todas las anteriores”, “ninguna de las anteriores” o combinaciones equivalentes.", "fix_hint": "Sustituir por distractores específicos.", "severity": "error"},
    "W101_STEM_NEG_LOWER": {"message": "Negación en minúscula en el enunciado; debe ir en MAYÚSCULAS.", "fix_hint": "Reformular en positivo o poner la negación en mayúsculas.", "severity": "warning"},
    "W102_ABSOL_STEM": {"message": "Uso de absolutos en el enunciado.", "fix_hint": "Sustituir absolutos por formulaciones más matizadas.", "severity": "warning"},
    "W103_HEDGE_STEM": {"message": "Expresión hedging innecesaria en el enunciado.", "fix_hint": "Eliminar o precisar la afirmación.", "severity": "warning"},
    "W105_LEXICAL_CUE": {"message": "Palabra clave del enunciado solo presente en la opción correcta.", "fix_hint": "Añadir la palabra clave a un distractor o reformular.", "severity": "warning"},
    "W108_ALT_VAGUE": {"message": "alt_text vago, genérico o con información irrelevante.", "fix_hint": "Describir los elementos clave relevantes para la accesibilidad.", "severity": "warning"},
    "W109_PLAUSIBILITY": {"message": "Distractor demasiado absurdo o fácilmente descartable.", "fix_hint": "Ajustar el distractor para representar un error conceptual plausible.", "severity": "warning"},
    "W112_DISTRACTOR_SIMILAR": {"message": "Dos o más distractores son demasiado similares entre sí.", "fix_hint": "Reformular distractores para representar errores diferentes.", "severity": "warning"},
    "W113_VAGUE_QUANTIFIER": {"message": "Cuantificador vago en el enunciado.", "fix_hint": "Sustituir por cuantificador preciso o reformular.", "severity": "warning"},
    "W114_OPTION_NO_PERIOD": {"message": "Las opciones terminan en punto final.", "fix_hint": "Eliminar el punto final.", "severity": "warning"},
    "W115_OPTION_NO_AND_IN_SERIES": {"message": "Conjunción “y” u “o” antes del último elemento de una serie con comas.", "fix_hint": "Eliminar la conjunción redundante.", "severity": "warning"},
    "W125_DESCRIPCION_DEFICIENTE": {"message": "Descripción visual poco informativa o faltante.", "fix_hint": "Mejorar la descripción para que sea concisa y completa.", "severity": "warning"},
    "W130_LANGUAGE_MISMATCH": {"message": "Mezcla inadvertida de idiomas en el ítem.", "fix_hint": "Unificar el idioma del enunciado y las opciones.", "severity": "warning"},
    "W199_UNCATEGORIZED_STYLE": {"message": "Problema de estilo no clasificado.", "fix_hint": "Revisar manualmente el estilo del ítem.", "severity": "warning"},

    # LOGICO
    "E070_NO_CORRECT_RATIONALE": {"message": "Falta la justificación de la opción correcta.", "fix_hint": "Añadir texto explicativo en la justificación de la opción correcta.", "severity": "error"},
    "E071_CALCULO_INCORRECTO": {"message": "Cálculo incorrecto en la opción correcta.", "fix_hint": "Verificar procedimiento matemático y resultado final.", "severity": "error"},
    "E072_UNIDADES_INCONSISTENTES": {"message": "Unidades o magnitudes inconsistentes entre enunciado y opciones.", "fix_hint": "Asegurar consistencia de unidades y magnitudes.", "severity": "error"},
    "E073_CONTRADICCION_INTERNA": {"message": "Información contradictoria o inconsistencia lógica interna.", "fix_hint": "Revisar y corregir la coherencia de datos y principios.", "severity": "fatal"},
    "E074_NIVEL_COGNITIVO_INAPROPIADO": {"message": "El ítem no coincide con el nivel cognitivo declarado.", "fix_hint": "Ajustar el nivel declarado o reformular el ítem.", "severity": "fatal"},
    "E075_DESCONOCIDO_LOGICO": {"message": "Error lógico no clasificado. Se refiere a problemas de coherencia interna o cálculo no cubiertos por otros códigos E07x.", "fix_hint": "Revisar manualmente la lógica del ítem.", "severity": "fatal"},
    "E076_DISTRACTOR_RATIONALE_MISMATCH": {"message": "La justificación del distractor no es clara o no se alinea con un error conceptual plausible.", "fix_hint": "Reformular la justificación del distractor para que sea clara y refleje un error conceptual común o plausible.", "severity": "error"},
    "E092_JUSTIFICA_INCONGRUENTE": {"message": "La justificación contradice la opción correspondiente.", "fix_hint": "Alinear la justificación con el contenido de la opción.", "severity": "error"},

    # ESTRUCTURAL
    "E001_SCHEMA": {"message": "El JSON del ítem no cumple el esquema.", "fix_hint": "Regenerar el ítem siguiendo el esquema.", "severity": "fatal"},
    "E010_NUM_OPTIONS": {"message": "El número de opciones debe ser 3 o 4.", "fix_hint": "Ajustar la cantidad de opciones.", "severity": "fatal"},
    "E011_DUP_ID": {"message": "IDs de opciones duplicados.", "fix_hint": "Usar IDs únicos.", "severity": "fatal"},
    "E012_CORRECT_COUNT": {"message": "Debe haber exactamente una opción correcta.", "fix_hint": "Dejar solo una opción con es_correcta: true.", "severity": "fatal"},
    "E013_ID_NO_MATCH": {"message": "respuesta_correcta_id no coincide con la opción correcta.", "fix_hint": "Sincronizar respuesta_correcta_id con el id de la opción correcta.", "severity": "fatal"},
    "E030_COMPLET_SEGMENTS": {"message": "Segmentos de opciones no coinciden con huecos del enunciado.", "fix_hint": "Alinear segmentos con huecos.", "severity": "fatal"},
    "E050_BAD_URL": {"message": "URL no válida o inaccesible.", "fix_hint": "Proveer URL accesible o dejar recurso_visual en null.", "severity": "fatal"},
    "E060_MULTI_TESTLET": {"message": "testlet_id y estimulo_compartido desincronizados.", "fix_hint": "Sincronizarlos o eliminarlos.", "severity": "fatal"},

    # POLITICAS
    "E090_CONTENIDO_OFENSIVO": {"message": "Contenido ofensivo, obsceno, violento o ilegal.", "fix_hint": "Reescribir para eliminar contenido inapropiado.", "severity": "fatal"},
    "E120_SESGO_GENERO": {"message": "Sesgo o estereotipos de género.", "fix_hint": "Usar lenguaje neutral o ejemplos equilibrados.", "severity": "error"},
    "E121_SESGO_CULTURAL_ETNICO": {"message": "Sesgo cultural o étnico.", "fix_hint": "Usar referencias culturalmente sensibles.", "severity": "error"},
    "E129_LENGUAJE_DISCRIMINATORIO": {"message": "Lenguaje discriminatorio o peyorativo.", "fix_hint": "Sustituir por formulaciones inclusivas.", "severity": "error"},
    "E130_ACCESIBILIDAD_CONTENIDO": {"message": "Contenido no accesible.", "fix_hint": "Proveer alternativas textuales o formatos accesibles.", "severity": "error"},
    "E140_TONO_INAPROPIADO_ACADEMICO": {"message": "Tono o lenguaje inapropiado para contexto académico.", "fix_hint": "Ajustar a registro formal.", "severity": "error"},
    "W141_CONTENIDO_TRIVIAL": {"message": "Contenido trivial o irrelevante.", "fix_hint": "Alinear con objetivos de aprendizaje.", "severity": "warning"},
    "W142_SESGO_IMPLICITO": {"message": "Sesgo implícito leve detectado.", "fix_hint": "Revisar ejemplos y lenguaje para neutralidad.", "severity": "warning"},

    # CONTENIDO
    "E200_CONTENT_MISALIGNMENT": {"message": "El contenido del ítem no se alinea con la metadata (tema, nivel, habilidad, etc.).", "fix_hint": "Ajustar el contenido del ítem para que refleje los parámetros de la metadata o viceversa.", "severity": "error"},
    "E201_CONCEPTUAL_ERROR": {"message": "El ítem contiene un error conceptual o factual en su contenido.", "fix_hint": "Corregir el error conceptual o factual en el enunciado, opciones o justificaciones.", "severity": "fatal"},
    "E202_DISTRACTOR_CONCEPTUAL_FLAW": {"message": "Un distractor es conceptualmente inverosímil o no representa un error pedagógicamente relevante.", "fix_hint": "Reformular el distractor para que sea plausible y represente un error conceptual común.", "severity": "error"},
    "E203_MULTIPLE_CONSTRUCTS": {"message": "El ítem evalúa múltiples conceptos o habilidades principales.", "fix_hint": "Simplificar el ítem para que evalúe un único constructo o habilidad.", "severity": "error"},
    "E299_UNCLASSIFIED_CONTENT_ERROR": {"message": "Error de contenido no clasificado. Requiere revisión manual.", "fix_hint": "Revisar el contenido del ítem para identificar el problema no tipificado.", "severity": "fatal"},

    # LLM_SISTEMA
    "E901_LLM_GEN_QUALITY_LOW": {"message": "Contenido generado incoherente o de baja calidad.", "fix_hint": "Reintentar generación o ajustar prompt.", "severity": "fatal"},
    "E902_LLM_CONTEXT_OVERFLOW": {"message": "Límite de tokens excedido.", "fix_hint": "Reducir tamaño de input o usar modelo con mayor ventana.", "severity": "fatal"},
    "E903_LLM_SAFETY_VIOLATION": {"message": "Contenido generado viola políticas de seguridad.", "fix_hint": "Ajustar prompt para evitar contenido sensible.", "severity": "fatal"},
    "E904_LLM_RESPONSE_FORMAT_ERROR": {"message": "La respuesta del LLM no es JSON válido o falta campos.", "fix_hint": "Revisar prompt para asegurar formato correcto.", "severity": "fatal"},
    "E905_LLM_CALL_FAILED": {"message": "Fallo en la llamada al LLM.", "fix_hint": "Revisar configuración o conexión.", "severity": "fatal"},
    "E907_UNEXPECTED_LLM_PROCESSING_ERROR": {"message": "Error inesperado procesando la respuesta del LLM.", "fix_hint": "Revisar logs para detalles.", "severity": "fatal"},

    # PIPELINE_CONTROL
    "E951_PROMPT_NOT_FOUND": {"message": "Prompt de etapa no encontrado.", "fix_hint": "Verificar ruta del archivo de prompt.", "severity": "fatal"},
    "E952_NO_PAYLOAD": {"message": "Ítem sin payload para procesar.", "fix_hint": "Revisar etapas anteriores.", "severity": "fatal"},
    "E953_ITEM_ID_MISMATCH": {"message": "item_id devuelto no coincide con el esperado.", "fix_hint": "Revisar lógica de refinador.", "severity": "fatal"},
    "E954_GEN_INIT_MISMATCH": {"message": "Cantidad de ítems generados no coincide con la solicitada.", "fix_hint": "Revisar parámetros de generación.", "severity": "fatal"},
    "E955_GEN_NO_SUCCESSFUL_OUTPUT": {"message": "Ningún ítem con estado success en la generación.", "fix_hint": "Revisar prompt o modelo.", "severity": "fatal"},
    "E956_LLM_RESPONSE_FORMAT_INVALID": {"message": "Lista de ítems generada con formato inválido.", "fix_hint": "Revisar prompt de generación.", "severity": "fatal"},
    "E957_LLM_ITEM_COUNT_MISMATCH": {"message": "Número de ítems generados distinto al solicitado.", "fix_hint": "Ajustar prompt o modelo.", "severity": "fatal"},
    "E959_PIPELINE_FATAL_ERROR": {"message": "Error fatal inesperado en la etapa.", "fix_hint": "Revisar log para más detalles.", "severity": "fatal"},
}

def get_error_info(code: str) -> Dict[str, Any]:
    """Obtiene el mensaje, fix_hint y severidad de un código de error desde el catálogo centralizado."""
    return _ERROR_CATALOG_FLAT.get(code, {"message": f"Unknown error code: {code}.", "fix_hint": None, "severity": "error"})
