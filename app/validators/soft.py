
"""
soft.py

Validador "suave" de estilo para ítems de opción múltiple.

Detecta problemas de longitud, legibilidad, mezcla de idiomas, descripciones vagas
y coherencia entre opciones y sus justificaciones, asignando códigos conforme al
catálogo SIGIE versión 2025‑06‑29.

Devuelve una lista de hallazgos. Cada hallazgo es:

    {
        "code": str,                # Código de error/advertencia
        "message": str,             # Texto idéntico al catálogo
        "field": str,               # Ruta JSON al problema
        "severity": "error"|"warning",
        "fix_hint": str,            # Texto idéntico al catálogo
        "details": str | None       # Sólo para E040_OPTION_LENGTH
    }

El objetivo es mantener la terminología exacta y centralizar aquí la lógica,
para que los prompts sólo necesiten corregir sin replicar reglas.
"""

from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Dict, List

# --- Parámetros de longitud -------------------------------------------------

STEM_WORD_LIMIT = 60
STEM_CHAR_LIMIT = 250
OPT_WORD_LIMIT = 30
OPT_CHAR_LIMIT = 140

# --- Palabras para detección de idioma --------------------------------------

ENGLISH_MINI_STOP = {
    "the", "and", "is", "are", "in", "on", "with", "of", "for", "to"
}
SPANISH_MINI_STOP = {
    "el", "la", "los", "las", "y", "es", "son", "en", "con", "de", "para"
}

# Expresiones simples para detectar contradicción en justificación
NEGATIVE_PATTERNS = re.compile(
    r"""
    \b(no\s+es\s+correcta|incorrect[oa]|fals[oa]|error(?:e|)\b)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


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


def _justification_contradiction(option: Dict) -> bool:
    """
    Detecta si la justificación contradice la corrección de la opción.
    Regla heurística: palabras negativas presentes cuando es_correcta=True,
    o viceversa.
    """
    justif = option.get("justificacion", "")
    if not justif.strip():
        return False
    neg = bool(NEGATIVE_PATTERNS.search(justif))
    return (option.get("es_correcta") and neg) or (not option.get("es_correcta") and not neg)


# ------------------------- Validador principal ------------------------------

def validate_style(item: Dict) -> List[Dict]:
    findings: List[Dict] = []

    # 1. Longitud y variación de opciones (E040_OPTION_LENGTH)
    options = item.get("opciones", [])
    lengths = [_count_words(o.get("texto", "")) for o in options]
    char_lengths = [len(o.get("texto", "")) for o in options]
    if options:
        max_len = max(lengths)
        min_len = min(lengths)
        # Exceso
        for idx, (w, c, op) in enumerate(zip(lengths, char_lengths, options)):
            if w > OPT_WORD_LIMIT or c > OPT_CHAR_LIMIT:
                findings.append({
                    "code": "E040_OPTION_LENGTH",
                    "message": "Longitud de opciones desbalanceada o demasiado extensa.",
                    "field": f"opciones[{idx}].texto",
                    "severity": "error",
                    "fix_hint": "Igualar o acortar el texto de las opciones según corresponda.",
                    "details": "excess",
                })
        # Variación
        if min_len > 0 and max_len / min_len >= 2:
            findings.append({
                "code": "E040_OPTION_LENGTH",
                "message": "Longitud de opciones desbalanceada o demasiado extensa.",
                "field": "opciones",
                "severity": "error",
                "fix_hint": "Igualar o acortar el texto de las opciones según corresponda.",
                "details": "variation",
            })

    # 2. Descripción vaga de recurso visual (W108_ALT_VAGUE)
    if "alt_text" in item and len(item["alt_text"].split()) < 3:
        findings.append({
            "code": "W108_ALT_VAGUE",
            "message": "alt_text vago, genérico o con información irrelevante.",
            "field": "alt_text",
            "severity": "warning",
            "fix_hint": "Describir los elementos clave relevantes para la accesibilidad.",
            "details": None,
        })

    # 3. Mezcla de idiomas en ítem (W130_LANGUAGE_MISMATCH)
    stem = item.get("enunciado_pregunta", "")
    if _language_mismatch(stem):
        findings.append({
            "code": "W130_LANGUAGE_MISMATCH",
            "message": "Mezcla inadvertida de idiomas en el ítem.",
            "field": "enunciado_pregunta",
            "severity": "warning",
            "fix_hint": "Unificar el idioma del enunciado y las opciones.",
            "details": None,
        })

    # 4. Justificación que contradice opción (E092_JUSTIFICA_INCONGRUENTE)
    for idx, op in enumerate(options):
        if _justification_contradiction(op):
            findings.append({
                "code": "E092_JUSTIFICA_INCONGRUENTE",
                "message": "La justificación contradice la opción correspondiente.",
                "field": f"opciones[{idx}].justificacion",
                "severity": "error",
                "fix_hint": "Alinear la justificación con el contenido de la opción.",
                "details": None,
            })

    # 5. Opción correcta similar al enunciado (E091_CORRECTA_SIMILAR_STEM)
    correct_id = item.get("respuesta_correcta_id")
    correct = next((o for o in options if o.get("id") == correct_id), None)
    if correct:
        sim = _semantic_similarity(stem, correct.get("texto", ""))
        if sim > 0.8:
            findings.append({
                "code": "E091_CORRECTA_SIMILAR_STEM",
                "message": "Opción correcta demasiado similar al enunciado; revela la respuesta.",
                "field": f"opciones[{options.index(correct)}].texto",
                "severity": "error",
                "fix_hint": "Reformular enunciado u opción para evitar pistas obvias.",
                "details": None,
            })

    return findings
