## app/services/validators/soft.py
import re
import difflib
from app.core.constants import (
    NEG_WORDS,
    ABSOL_WORDS,
    COLOR_WORDS,
    HEDGE_WORDS,
    STOP_WORDS,
    FORBIDDEN_OPTIONS,
)


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def _semantic_similarity(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def _check_distractor_similarity(options):
    distractors = [o['texto'] for o in options if not o.get('es_correcta', False)]
    if len(distractors) < 2:
        return None
    sim_scores = []
    for i in range(len(distractors)):
        for j in range(i + 1, len(distractors)):
            sim_scores.append(_semantic_similarity(distractors[i], distractors[j]))
    avg_sim = sum(sim_scores) / len(sim_scores)
    if avg_sim > 0.85:
        return {
            "warning_code": "W112",
            "message": "Distractores presentan alta similitud semántica entre sí."
        }
    return None

def _check_stem_correct_similarity(item):
    stem = item.get("enunciado_pregunta", "")
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    correct = next((o for o in options if o.get("id") == correct_id), None)
    distractors = [o for o in options if o.get("id") != correct_id]
    if not correct or not distractors:
        return None
    correct_sim = _semantic_similarity(stem, correct["texto"])
    distractor_sim = [_semantic_similarity(stem, d["texto"]) for d in distractors]
    if correct_sim > 0.8 and all(ds < 0.5 for ds in distractor_sim):
        return {
            "warning_code": "E091",
            "message": "Solo la opción correcta es semánticamente similar al enunciado, lo que puede revelar la respuesta."
        }
    return None

def _check_alt_text(item):
    alt = item.get("alt_text", "").lower()
    issues = []
    if any(color in alt for color in COLOR_WORDS):
        issues.append({
            "warning_code": "W107",
            "message": "alt_text menciona colores sin codificar información relevante."
        })
    if len(alt.split()) < 5:
        issues.append({
            "warning_code": "W108",
            "message": "alt_text vago o genérico."
        })
    return issues

def _check_quantifier_vagueness(stem):
    vague_patterns = [r"\balgunos\b", r"\bmuchos\b", r"\ben\s+general\b", r"\ba\s+veces\b", r"\balgunas\b"]
    for pattern in vague_patterns:
        if re.search(pattern, stem):
            return {
                "warning_code": "W113",
                "message": "Cuantificador vago detectado en el enunciado."
            }
    return None

def soft_validate(item: dict) -> list[dict]:
    warnings = []

    stem = item.get("enunciado_pregunta", "").lower()
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")

    # Negaciones en minúscula
    if any(f" {neg} " in stem for neg in NEG_WORDS):
        warnings.append({"warning_code": "W101", "message": "Negación en minúscula detectada."})

    # Absolutos
    if any(f" {absol} " in stem for absol in ABSOL_WORDS):
        warnings.append({"warning_code": "W102", "message": "Uso de absolutos en el stem."})

    # Hedging
    if any(f" {hedge} " in stem for hedge in HEDGE_WORDS):
        warnings.append({"warning_code": "W103", "message": "Expresión hedging innecesaria en el stem."})

    # Cuantificadores vagos
    vague = _check_quantifier_vagueness(stem)
    if vague:
        warnings.append(vague)

    # Frases prohibidas en opciones
    for opt in options:
        for f in FORBIDDEN_OPTIONS:
            if f in opt.get("texto", "").lower():
                warnings.append({"warning_code": "W106", "message": f"Frase prohibida en la opción {opt['id']}."})

    # Homogeneidad de longitud entre opciones
    lengths = [count_words(opt.get("texto", "")) for opt in options if opt.get("texto")]
    if lengths and max(lengths) / min(lengths) > 1.25:
        warnings.append({"warning_code": "W104", "message": "Variación excesiva en la longitud de opciones."})

    # Pistas léxicas
    correct_opt = next((o for o in options if o["id"] == correct_id), None)
    if correct_opt:
        correct_tokens = set(re.findall(r"\b\w+\b", correct_opt["texto"].lower())) - STOP_WORDS
        stem_tokens = set(re.findall(r"\b\w+\b", stem)) - STOP_WORDS
        if len(correct_tokens & stem_tokens) >= 2:
            warnings.append({"warning_code": "W105", "message": "Pista léxica en la opción correcta."})

    # Similitud entre distractores
    sim_warn = _check_distractor_similarity(options)
    if sim_warn:
        warnings.append(sim_warn)

    # Similitud entre stem y correcta
    sim_corr = _check_stem_correct_similarity(item)
    if sim_corr:
        warnings.append(sim_corr)

    # Validaciones de alt_text
    warnings.extend(_check_alt_text(item))

    return warnings
