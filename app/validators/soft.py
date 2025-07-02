# app/validators/soft.py
from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional

# --- Importamos las constantes necesarias desde app.core.constants ---
from app.core.constants import (
    NEG_WORDS,
    ABSOL_WORDS,
    COLOR_WORDS,
    HEDGE_WORDS,
    STOP_WORDS,
    FORBIDDEN_OPTIONS,
)
# Nuevo import desde el módulo centralizado de metadata de errores
from app.core.error_metadata import get_error_info as get_centralized_error_info

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

# ELIMINADO: MOCK_ERROR_CATALOG_SOFT

# La función get_error_info ahora usa la versión centralizada
def get_error_info(code: str) -> dict:
    """Helper para obtener mensaje, fix_hint y severidad del catálogo centralizado."""
    return get_centralized_error_info(code)


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
            "message": info["message"],
            "severity": info["severity"]
        }
    return None

# ELIMINADO: _check_plausibility_w109() si existía una función explícita para W109 de contenido.
# La validación de W109_PLAUSIBILITY en soft.py se dejará para problemas de "absurdez" superficial/estilística,
# no para la plausibilidad conceptual profunda que ahora es de E202_DISTRACTOR_CONCEPTUAL_FLAW.
# Si existía código explícito en soft.py para W109 que realizaba un análisis de contenido profundo, se eliminaría aquí.
# Basado en el código actual, W109 no tiene una función dedicada.


def _check_stem_correct_similarity(item: Dict) -> Optional[Dict]:
    stem_text = item.get("enunciado_pregunta", "")
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    correct = next((o for o in options if o.get("id") == correct_id), None)
    distractors = [o for o in options if o.get("id") != correct_id]
    if not correct or not distractors:
        return [] # Return empty list to match new expected type for alt_text_issues in soft_validate
    correct_sim = _semantic_similarity(stem_text, correct["texto"])
    distractor_sim = [_semantic_similarity(stem_text, d["texto"]) for d in distractors]
    if correct_sim > 0.8 and all(ds < 0.5 for ds in distractor_sim):
        info = get_error_info("E091_CORRECTA_SIMILAR_STEM")
        return {
            "code": "E091_CORRECTA_SIMILAR_STEM",
            "message": info["message"],
            "severity": info["severity"]
        }
    return None

def _check_alt_text(item: Dict) -> List[Dict]:
    visual_resource = item.get("recurso_visual")
    if not visual_resource:
        return []

    alt = visual_resource.get("alt_text", "").lower()
    issues = []

    is_vague_or_too_short = (len(alt.split()) < 5 and len(alt) > 0)
    missing_descriptive_verb = not any(verb in alt for verb in DESCRIPTIVE_VERBS)
    mentions_color_without_coding_info = any(color in alt for color in COLOR_WORDS)

    if is_vague_or_too_short or missing_descriptive_verb or mentions_color_without_coding_info:
        info = get_error_info("W108_ALT_VAGUE")
        issues.append({
            "code": "W108_ALT_VAGUE",
            "message": info["message"],
            "severity": info["severity"]
        })
    return issues

def _check_quantifier_vagueness(stem_text: str) -> Optional[Dict]:
    vague_patterns = [r"\\balgunos\\b", r"\\bmuchos\\b", r"\\ben\\s+general\\b", r"\\ba\\s+veces\\b", r"\\balgunas\\b"]
    for pattern in vague_patterns:
        if re.search(pattern, stem_text):
            info = get_error_info("W113_VAGUE_QUANTIFIER")
            return {
                "code": "W113_VAGUE_QUANTIFIER",
                "message": info["message"],
                "severity": info["severity"]
            }
    return None

# ------------------------- Validador principal ------------------------------

def soft_validate(item: Dict) -> List[Dict]:
    findings: List[Dict] = []

    stem_text = item.get("enunciado_pregunta", "")
    stem_lower = stem_text.lower()
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    recurso_visual = item.get("recurso_visual")

    # 1. Longitud y variación de opciones (E040_OPTION_LENGTH)
    lengths = [_count_words(o.get("texto", "")) for o in options]
    char_lengths = [len(o.get("texto", "")) for o in options]
    if options:
        max_len = max(lengths)
        min_len = min(lengths)
        # Exceso
        for idx, (w, c, op) in enumerate(zip(lengths, char_lengths, options)):
            if w > OPT_WORD_LIMIT or c > OPT_CHAR_LIMIT:
                code = "E040_OPTION_LENGTH"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"],
                    "field": f"opciones[{op.get('id', idx)}].texto",
                    "severity": info["severity"],
                    "fix_hint": info["fix_hint"],
                    "details": "excess",
                })
        # Variación
        if min_len > 0 and max_len / min_len >= 2:
            code = "E040_OPTION_LENGTH"
            info = get_error_info(code)
            findings.append({
                "code": code,
                "message": info["message"],
                "field": "opciones",
                "severity": info["severity"],
                "fix_hint": info["fix_hint"],
                "details": "variation",
            })
    elif len(options) > 0 and all(not opt.get("texto").strip() for opt in options):
        pass

    # 2. Descripción vaga de recurso visual (W108_ALT_VAGUE)
    alt_text_issues = _check_alt_text(item)
    if alt_text_issues:
        for issue in alt_text_issues:
            # issue ya contiene code, message y severity de _check_alt_text
            info = get_error_info(issue["code"])
            findings.append({
                **issue,
                "field": issue.get("field", "recurso_visual.alt_text"),
                "fix_hint": info["fix_hint"],
                "details": None,
            })

    # 3. Mezcla de idiomas en ítem (W130_LANGUAGE_MISMATCH)
    if _language_mismatch(stem_text):
        code = "W130_LANGUAGE_MISMATCH"
        info = get_error_info(code)
        findings.append({
            "code": code,
            "message": info["message"],
            "field": "enunciado_pregunta",
            "severity": info["severity"],
            "fix_hint": info["fix_hint"],
            "details": None,
        })

    # 5. Opción correcta similar al enunciado (E091_CORRECTA_SIMILAR_STEM)
    if correct_id and stem_lower:
        sim_corr_finding = _check_stem_correct_similarity(item)
        if sim_corr_finding:
            # sim_corr_finding ya contiene code, message y severity
            info = get_error_info(sim_corr_finding["code"])
            findings.append({
                **sim_corr_finding,
                "field": f"opciones[{next((o for o in options if o['id'] == correct_id), {}).get('id', correct_id)}].texto",
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
                "severity": info["severity"],
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
                "severity": info["severity"],
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
            "severity": info["severity"],
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
            "severity": info["severity"],
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
            "severity": info["severity"],
            "fix_hint": info["fix_hint"]
        })

    # W113_VAGUE_QUANTIFIER
    vague_finding = _check_quantifier_vagueness(stem_text)
    if vague_finding:
        # vague_finding ya contiene code, message y severity
        info = get_error_info(vague_finding["code"])
        findings.append({
            **vague_finding,
            "field": "enunciado_pregunta",
            "fix_hint": info["fix_hint"]
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
                "severity": info["severity"],
                "fix_hint": info["fix_hint"]
            })
            break

    # W104_OPT_LEN_VAR (Homogeneidad de longitud)
    # Re-introducido y ajustado para que sea una validación de estilo.
    # Anteriormente se comentó, pero es relevante para la homogeneidad de estilo.
    if options:
        valid_lengths = [_count_words(o.get("texto", "")) for o in options if o.get("texto") and _count_words(o.get("texto", "")) > 0]
        if valid_lengths:
            min_len = min(valid_lengths)
            max_len = max(valid_lengths)
            if min_len > 0 and max_len / min_len >= 2:
                code = "W104_OPT_LEN_VAR"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"],
                    "field": "opciones",
                    "severity": info["severity"],
                    "fix_hint": info["fix_hint"]
                })

    # W105_LEXICAL_CUE
    if correct_id and stem_lower:
        correct_opt = next((o for o in options if o["id"] == correct_id), None)
        if correct_opt and correct_opt["texto"]:
            correct_tokens = set(re.findall(r"\\b\\w+\\b", correct_opt["texto"].lower())) - STOP_WORDS
            stem_tokens = set(re.findall(r"\\b\\w+\\b", stem_lower)) - STOP_WORDS
            if len(correct_tokens.intersection(stem_tokens)) >= 2:
                code = "W105_LEXICAL_CUE"
                info = get_error_info(code)
                findings.append({
                    "code": code,
                    "message": info["message"],
                    "field": f"opciones[{correct_opt['id']}].texto",
                    "severity": info["severity"],
                    "fix_hint": info["fix_hint"]
                })

    # W112_DISTRACTOR_SIMILAR
    sim_warn = _check_distractor_similarity(options)
    if sim_warn:
        # sim_warn ya contiene code, message y severity
        info = get_error_info(sim_warn["code"])
        findings.append({
            **sim_warn,
            "field": "opciones",
            "fix_hint": info["fix_hint"]
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
                "severity": info["severity"],
                "fix_hint": info["fix_hint"]
            })

    # W109_PLAUSIBILITY: No hay una función dedicada o validación explícita para W109 de contenido profundo aquí.
    # W109_PLAUSIBILITY en soft.py se refiere a "Distractor demasiado absurdo o fácilmente descartable"
    # Este se mantiene en el error_codes.yaml y en el refinador de estilo.
    # Se entiende que la "absurdez" a nivel de estilo/redacción es distinta a la "inverosimilitud conceptual" (E202).

    return findings
