# app/validators/soft.py
from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional # Asegurar Optional y Any estén importados correctamente

# --- Importamos las constantes necesarias desde app.core.constants ---
# Eliminamos las que se definen localmente en este archivo para evitar warnings de unused imports.
from app.core.constants import (
    NEG_WORDS,
    ABSOL_WORDS,
    COLOR_WORDS,
    HEDGE_WORDS,
    STOP_WORDS,
    FORBIDDEN_OPTIONS,
)

# --- Parámetros de longitud (Definiciones locales para soft.py para claridad y evitar unused imports) ---
STEM_WORD_LIMIT = 60
STEM_CHAR_LIMIT = 250
OPT_WORD_LIMIT = 30
OPT_CHAR_LIMIT = 140

# --- Palabras para detección de idioma (Definiciones locales para soft.py) ---
ENGLISH_MINI_STOP = {
    "the", "and", "is", "are", "in", "on", "with", "of", "for", "to"
}
SPANISH_MINI_STOP = {
    "el", "la", "los", "las", "y", "es", "son", "en", "con", "de", "para"
}

# Temporal list of descriptive verbs for W108_ALT_VAGUE.
DESCRIPTIVE_VERBS = ["muestra", "indica", "representa", "describe", "ilustra", "contiene", "detalla", "explica", "compara", "presenta", "resume", "provee", "visualiza"]


# MOCK: En un sistema real, este catálogo se cargaría desde sigie_error_codes.yaml
# o a través de un módulo de utilidades centralizado.
# Contiene solo los códigos relevantes para soft.py con sus mensajes y fix_hints.
MOCK_ERROR_CATALOG_SOFT = {
    "E020_STEM_LENGTH": {"message": "Enunciado excede límite de longitud.", "fix_hint": "Recortar el enunciado sin perder claridad."},
    "E040_OPTION_LENGTH": {"message": "Longitud de opciones desbalanceada o demasiado extensa.", "fix_hint": "Igualar o acortar el texto de las opciones según corresponda."},
    "E080_MATH_FORMAT": {"message": "Mezcla de Unicode y LaTeX o formato matemático inconsistente.", "fix_hint": "Usar un solo sistema de notación de forma consistente."},
    "E091_CORRECTA_SIMILAR_STEM": {"message": "Opción correcta demasiado similar al enunciado; revela la respuesta.", "fix_hint": "Reformular enunciado u opción para evitar pistas obvias."},
    "E106_COMPLEX_OPTION_TYPE": {"message": "Se usó “todas las anteriores”, “ninguna de las anteriores” o combinaciones equivalentes.", "fix_hint": "Sustituir por distractores específicos."},
    "W101_STEM_NEG_LOWER": {"message": "Negación en minúscula en el enunciado; debe ir en MAYÚSCULAS.", "fix_hint": "Reformular en positivo o poner la negación en mayúsculas."},
    "W102_ABSOL_STEM": {"message": "Uso de absolutos en el enunciado.", "fix_hint": "Sustituir absolutos por formulaciones más matizadas."},
    "W103_HEDGE_STEM": {"message": "Expresión hedging innecesaria en el enunciado.", "fix_hint": "Eliminar o precisar la afirmación."},
    "W105_LEXICAL_CUE": {"message": "Palabra clave del enunciado solo presente en la opción correcta.", "fix_hint": "Añadir la palabra clave a un distractor o reformular."},
    "W108_ALT_VAGUE": {"message": "alt_text vago, genérico o con información irrelevante.", "fix_hint": "Describir los elementos clave relevantes para la accesibilidad."},
    "W109_PLAUSIBILITY": {"message": "Distractor demasiado absurdo o fácilmente descartable.", "fix_hint": "Ajustar el distractor para representar un error conceptual plausible."},
    "W112_DISTRACTOR_SIMILAR": {"message": "Dos o más distractores son demasiado similares entre sí.", "fix_hint": "Reformular distractores para representar errores diferentes."},
    "W113_VAGUE_QUANTIFIER": {"message": "Cuantificador vago en el enunciado.", "fix_hint": "Sustituir por cuantificador preciso o reformular."},
    "W114_OPTION_NO_PERIOD": {"message": "Las opciones terminan en punto final.", "fix_hint": "Eliminar el punto final."},
    "W115_OPTION_NO_AND_IN_SERIES": {"message": "Conjunción “y” u “o” antes del último elemento de una serie con comas.", "fix_hint": "Eliminar la conjunción redundante."},
    "W125_DESCRIPCION_DEFICIENTE": {"message": "Descripción visual poco informativa o faltante.", "fix_hint": "Mejorar la descripción para que sea concisa y completa."},
    "W130_LANGUAGE_MISMATCH": {"message": "Mezcla inadvertida de idiomas en el ítem.", "fix_hint": "Unificar el idioma del enunciado y las opciones."},
}

def get_error_info(code: str) -> dict:
    """Helper to get message and fix_hint from the mock catalog."""
    return MOCK_ERROR_CATALOG_SOFT.get(code, {"message": f"Unknown error code: {code}.", "fix_hint": None})


# ------------------------ Funciones auxiliares ------------------------------

def _count_words(text: str) -> int:
    return len(re.findall(r'\w+', text))


def _semantic_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _language_mismatch(text: str) -> bool:
    """
    Devuelve True si se detectan palabras inglesas y españolas mezcladas.
    """
    tokens = re.findall(r'\b[a-záéíóúñü]+\b', text.lower())
    if not tokens:
        return False
    english = any(t in ENGLISH_MINI_STOP for t in tokens)
    spanish = any(t in SPANISH_MINI_STOP for t in tokens)
    return english and spanish


# _justification_contradiction ha sido eliminada por decisión del usuario.
# NEGATIVE_PATTERNS también se elimina ya que solo era usado por _justification_contradiction.


def _check_distractor_similarity(options: List[Dict]) -> Optional[Dict]:
    distractors = [o['texto'] for o in options if not o.get('es_correcta', False)]
    if len(distractors) < 2:
        return None
    sim_scores = []
    for i in range(len(distractors)):
        for j in range(i + 1, len(distractors)):
            sim_scores.append(_semantic_similarity(distractors[i], distractors[j]))
    avg_sim = sum(sim_scores) / len(sim_scores)
    if avg_sim > 0.85:
        info = get_error_info("W112_DISTRACTOR_SIMILAR")
        return {
            "code": "W112_DISTRACTOR_SIMILAR",
            "message": info["message"]
        }
    return None

def _check_stem_correct_similarity(item: Dict) -> Optional[Dict]:
    # `stem` no se pasa directamente, se obtiene del `item` dentro de la función.
    stem_text = item.get("enunciado_pregunta", "") # Definición local para esta función auxiliar
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    correct = next((o for o in options if o.get("id") == correct_id), None)
    distractors = [o for o in options if o.get("id") != correct_id]
    if not correct or not distractors:
        return None
    correct_sim = _semantic_similarity(stem_text, correct["texto"]) # Usar stem_text definido localmente
    distractor_sim = [_semantic_similarity(stem_text, d["texto"]) for d in distractors] # Usar stem_text
    if correct_sim > 0.8 and all(ds < 0.5 for ds in distractor_sim):
        info = get_error_info("E091_CORRECTA_SIMILAR_STEM")
        return {
            "code": "E091_CORRECTA_SIMILAR_STEM",
            "message": info["message"]
        }
    return None

def _check_alt_text(item: Dict) -> List[Dict]:
    visual_resource = item.get("recurso_visual")
    if not visual_resource:
        return []

    alt = visual_resource.get("alt_text", "").lower()
    issues = []

    is_vague_or_too_short = (len(alt.split()) < 5 and len(alt) > 0)
    # DESCRIPTIVE_VERBS está temporalmente aquí, debería venir de constants.py
    missing_descriptive_verb = not any(verb in alt for verb in DESCRIPTIVE_VERBS)
    mentions_color_without_coding_info = any(color in alt for color in COLOR_WORDS)

    if is_vague_or_too_short or missing_descriptive_verb or mentions_color_without_coding_info:
        info = get_error_info("W108_ALT_VAGUE")
        issues.append({
            "code": "W108_ALT_VAGUE",
            "message": info["message"]
        })
    return issues

def _check_quantifier_vagueness(stem_text: str) -> Optional[Dict]: # Cambiado a stem_text para claridad
    vague_patterns = [r"\\balgunos\\b", r"\\bmuchos\\b", r"\\ben\\s+general\\b", r"\\ba\\s+veces\\b", r"\\balgunas\\b"]
    for pattern in vague_patterns:
        if re.search(pattern, stem_text): # Usar stem_text
            info = get_error_info("W113_VAGUE_QUANTIFIER")
            return {
                "code": "W113_VAGUE_QUANTIFIER",
                "message": info["message"]
            }
    return None

# ------------------------- Validador principal ------------------------------

def soft_validate(item: Dict) -> List[Dict]:
    findings: List[Dict] = []

    stem_text = item.get("enunciado_pregunta", "")
    stem_lower = stem_text.lower() # Esta es la variable 'stem' en el contexto del linter.
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    recurso_visual = item.get("recurso_visual")

    # 1. Longitud y variación de opciones (E040_OPTION_LENGTH)
    lengths = [_count_words(o.get("texto", "")) for o in options]
    char_lengths = [len(o.get("texto", "")) for o in options]
    if options: # Asegurarse de que haya opciones antes de calcular min/max
        max_len = max(lengths)
        min_len = min(lengths)
        # Exceso
        for idx, (w, c, op) in enumerate(zip(lengths, char_lengths, options)):
            if w > OPT_WORD_LIMIT or c > OPT_CHAR_LIMIT:
                code = "E040_OPTION_LENGTH"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"], # Usar mensaje del catálogo
                    "field": f"opciones[{op.get('id', idx)}].texto", # Usar ID de opción si está disponible
                    "severity": "error",
                    "fix_hint": info["fix_hint"], # Incluir fix_hint
                    "details": "excess",
                })
        # Variación
        if min_len > 0 and max_len / min_len >= 2:
            code = "E040_OPTION_LENGTH"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"], # Usar mensaje del catálogo
                "field": "opciones",
                "severity": "error",
                "fix_hint": info["fix_hint"], # Incluir fix_hint
                "details": "variation",
            })
    # Este caso de opciones vacías o sin palabras (que antes se trataba aquí)
    # se omite ahora para alinear con la definición de E040 en el catálogo.
    elif len(options) > 0 and all(not opt.get("texto").strip() for opt in options):
        pass


    # 2. Descripción vaga de recurso visual (W108_ALT_VAGUE) - Ahora en _check_alt_text
    alt_text_issues = _check_alt_text(item)
    if alt_text_issues:
        for issue in alt_text_issues: # _check_alt_text ya devuelve el code y message
            info = get_error_info(issue["code"]) # Usar el info para obtener el fix_hint
            findings.append({
                **issue, # Ya incluye code y message
                "field": issue.get("field", "recurso_visual.alt_text"), # Asegurar el field
                "severity": "warning",
                "fix_hint": info["fix_hint"], # Incluir fix_hint
                "details": None,
            })

    # 3. Mezcla de idiomas en ítem (W130_LANGUAGE_MISMATCH)
    if _language_mismatch(stem_text): # Usar stem_text
        code = "W130_LANGUAGE_MISMATCH"
        info = get_error_info(code)
        findings.append({
            "code": code,
            "message": info["message"],
            "field": "enunciado_pregunta",
            "severity": "warning",
            "fix_hint": info["fix_hint"],
            "details": None,
        })

    # 4. Justificación que contradice opción (E092_JUSTIFICA_INCONGRUENTE) - ELIMINADO

    # 5. Opción correcta similar al enunciado (E091_CORRECTA_SIMILAR_STEM)
    # Se añade comprobación para correct_id y stem_lower
    if correct_id and stem_lower: # Solo si hay correct_id y stem_lower
        sim_corr_finding = _check_stem_correct_similarity(item) # Esto ya devuelve code y message
        if sim_corr_finding:
            info = get_error_info(sim_corr_finding["code"])
            findings.append({
                **sim_corr_finding, # Incluye code y message
                "field": f"opciones[{next((o for o in options if o['id'] == correct_id), {}).get('id', correct_id)}].texto", # Usar ID de opción o el correct_id
                "severity": "error",
                "fix_hint": info["fix_hint"],
                "details": None,
            })

    # --- Otras validaciones específicas con el catálogo optimizado ---

    # W114_OPTION_NO_PERIOD
    for i, opt in enumerate(options):
        if opt.get("texto", "").strip().endswith('.'):
            code = "W114_OPTION_NO_PERIOD"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"],
                "field": f"opciones[{opt.get('id', i)}].texto",
                "severity": "warning",
                "fix_hint": info["fix_hint"]
            })

    # W115_OPTION_NO_AND_IN_SERIES
    for i, opt in enumerate(options):
        opt_text = opt.get("texto", "")
        if re.search(r',\s*(?:y|o)\s+[^,]+$', opt_text, re.IGNORECASE):
            code = "W115_OPTION_NO_AND_IN_SERIES"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"],
                "field": f"opciones[{opt.get('id', i)}].texto",
                "severity": "warning",
                "fix_hint": info["fix_hint"]
            })

    # W101_STEM_NEG_LOWER
    if any(f" {neg} " in stem_lower for neg in NEG_WORDS):
        code = "W101_STEM_NEG_LOWER"
        info = get_error_info(code)
        findings.append({
            "code": code,
            "message": info["message"],
            "field": "enunciado_pregunta",
            "severity": "warning",
            "fix_hint": info["fix_hint"]
        })

    # W102_ABSOL_STEM
    if any(f" {absol} " in stem_lower for absol in ABSOL_WORDS):
        code = "W102_ABSOL_STEM"
        info = get_error_info(code)
        findings.append({
            "code": code,
            "message": info["message"],
            "field": "enunciado_pregunta",
            "severity": "warning",
            "fix_hint": info["fix_hint"]
        })

    # W103_HEDGE_STEM
    if any(f" {hedge} " in stem_lower for hedge in HEDGE_WORDS):
        code = "W103_HEDGE_STEM"
        info = get_error_info(code)
        findings.append({
            "code": code,
            "message": info["message"],
            "field": "enunciado_pregunta",
            "severity": "warning",
            "fix_hint": info["fix_hint"]
        })

    # W113_VAGUE_QUANTIFIER
    vague_finding = _check_quantifier_vagueness(stem_text) # Usar stem_text
    if vague_finding:
        # Asegurarse de que el código sea correcto antes de obtener info
        code = vague_finding.get("code")
        if code and code in MOCK_ERROR_CATALOG_SOFT: # Verificar que el código exista en el catálogo
            info = get_error_info(code)
            findings.append({
                **vague_finding, # Incluye code y message
                "field": "enunciado_pregunta",
                "severity": "warning",
                "fix_hint": info["fix_hint"]
            })
        else: # Fallback si el código de vague_finding no es el esperado o no está en el catálogo
            findings.append({
                "code": "W113_VAGUE_QUANTIFIER", # Fallback a código conocido si hay inconsistencia
                "message": "Cuantificador vago detectado en el enunciado.",
                "field": "enunciado_pregunta",
                "severity": "warning",
                "fix_hint": get_error_info("W113_VAGUE_QUANTIFIER").get("fix_hint")
            })

    # E106_COMPLEX_OPTION_TYPE
    for i, opt in enumerate(options):
        opt_lower = opt.get("texto", "").lower()
        if any(f in opt_lower for f in FORBIDDEN_OPTIONS):
            code = "E106_COMPLEX_OPTION_TYPE"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"],
                "field": f"opciones[{opt.get('id', i)}].texto",
                "severity": "error",
                "fix_hint": info["fix_hint"]
            })
            break

    # W104_OPT_LEN_VAR (Homogeneidad de longitud)
    # Lógica ajustada para ser más precisa y alineada con el catálogo.
    if options:
        valid_lengths = [_count_words(o.get("texto", "")) for o in options if o.get("texto") and _count_words(o.get("texto", "")) > 0]
        if valid_lengths:
            min_len = min(valid_lengths)
            max_len = max(valid_lengths)
            # Solo si hay suficiente variación para ser un problema
            if min_len > 0 and max_len / min_len >= 2: # Considera 2x como umbral
                code = "W104_OPT_LEN_VAR"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"],
                    "field": "opciones",
                    "severity": "warning",
                    "fix_hint": info["fix_hint"]
                })


    # W105_LEXICAL_CUE
    if correct_id and stem_lower: # Solo si hay correct_id y stem_lower
        correct_opt = next((o for o in options if o["id"] == correct_id), None)
        if correct_opt and correct_opt["texto"]:
            correct_tokens = set(re.findall(r"\\b\\w+\\b", correct_opt["texto"].lower())) - STOP_WORDS
            stem_tokens = set(re.findall(r"\\b\\w+\\b", stem_lower)) - STOP_WORDS
            if len(correct_tokens.intersection(stem_tokens)) >= 2: # Umbral de 2 palabras clave en común
                code = "W105_LEXICAL_CUE"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"],
                    "field": f"opciones[{correct_opt['id']}].texto",
                    "severity": "warning",
                    "fix_hint": info["fix_hint"]
                })


    # W112_DISTRACTOR_SIMILAR
    sim_warn = _check_distractor_similarity(options)
    if sim_warn:
        # Asegurarse de que el código sea correcto antes de obtener info
        code = sim_warn.get("code")
        if code and code in MOCK_ERROR_CATALOG_SOFT: # Verificar que el código exista en el catálogo
            info = get_error_info(code)
            findings.append({
                **sim_warn, # Ya incluye code y message
                "field": "opciones",
                "severity": "warning",
                "fix_hint": info["fix_hint"]
            })
        else: # Fallback si el código de sim_warn no es el esperado o no está en el catálogo
            findings.append({
                "code": "W112_DISTRACTOR_SIMILAR", # Fallback a código conocido si hay inconsistencia
                "message": "Distractores presentan alta similitud semántica entre sí.",
                "field": "opciones",
                "severity": "warning",
                "fix_hint": get_error_info("W112_DISTRACTOR_SIMILAR").get("fix_hint")
            })

    # W125_DESCRIPCION_DEFICIENTE
    if recurso_visual:
        description_text = recurso_visual.get("descripcion", "")
        if not description_text.strip() or _count_words(description_text) < 10:
            code = "W125_DESCRIPCION_DEFICIENTE"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"],
                "field": "recurso_visual.descripcion",
                "severity": "warning",
                "fix_hint": info["fix_hint"]
            })

    return findings
