# app/validators/soft.py
import re
import difflib
from app.core.constants import (
    NEG_WORDS,
    ABSOL_WORDS,
    COLOR_WORDS,
    HEDGE_WORDS,
    STOP_WORDS,
    FORBIDDEN_OPTIONS,
    STEM_W_LIMIT,
    STEM_C_LIMIT,
    OPT_W_LIMIT_NORM,
    OPT_C_LIMIT_NORM,
)


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def count_chars(text: str) -> int: # Nueva función para contar caracteres
    return len(text)

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
    if avg_sim > 0.85: # Umbral para considerar similitud alta
        return {
            "code": "W112_DISTRACTOR_SIMILAR", # Usar code estandarizado
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
    # Si la opción correcta es mucho más similar al enunciado que los distractores
    if correct_sim > 0.8 and all(ds < 0.5 for ds in distractor_sim): # Umbrales específicos
        return {
            "code": "E091_CORRECTA_SIMILAR_STEM", # Usar code estandarizado
            "message": "Solo la opción correcta es semánticamente similar al enunciado, lo que puede revelar la respuesta."
        }
    return None

def _check_alt_text(item):
    visual_resource = item.get("recurso_visual")
    if not visual_resource:
        return []

    alt = visual_resource.get("alt_text", "").lower()
    issues = []

    if any(color in alt for color in COLOR_WORDS):
        issues.append({
            "code": "W107_COLOR_ALT", # Usar code estandarizado
            "message": "alt_text menciona colores sin codificar información relevante."
        })
    if len(alt.split()) < 5 and len(alt) > 0: # Check for very short but not empty alt_text
        issues.append({
            "code": "W108_ALT_VAGUE", # Usar code estandarizado
            "message": "alt_text vago o genérico."
        })
    return issues

def _check_quantifier_vagueness(stem):
    vague_patterns = [r"\balgunos\b", r"\bmuchos\b", r"\ben\s+general\b", r"\ba\s+veces\b", r"\balgunas\b"]
    for pattern in vague_patterns:
        if re.search(pattern, stem):
            return {
                "code": "W113_VAGUE_QUANTIFIER", # Usar code estandarizado
                "message": "Cuantificador vago detectado en el enunciado."
            }
    return None

def soft_validate(item: dict) -> list[dict]:
    findings = [] # La lista se llama 'findings' para ser consistente con ReportEntrySchema

    stem_text = item.get("enunciado_pregunta", "")
    stem_lower = stem_text.lower()
    options = item.get("opciones", [])
    correct_id = item.get("respuesta_correcta_id")
    recurso_visual = item.get("recurso_visual") # Obtener el recurso visual para W125

    # --- NUEVAS VALIDACIONES DE ESTILO (Reclasificados a 'error' en el catálogo) ---

    # E020_STEM_LENGTH: Enunciado excede límite de longitud
    if count_words(stem_text) > STEM_W_LIMIT or count_chars(stem_text) > STEM_C_LIMIT:
        findings.append({
            "code": "E020_STEM_LENGTH",
            "message": f"Enunciado excede el límite de longitud ({STEM_W_LIMIT} palabras o {STEM_C_LIMIT} caracteres).",
            "field": "enunciado_pregunta"
        })

    # E040_OPTION_LENGTH: Alguna opción excede el límite de longitud
    for i, opt in enumerate(options):
        opt_text = opt.get("texto", "")
        # Usar OPT_W_LIMIT_NORM y OPT_C_LIMIT_NORM para opciones normales
        if count_words(opt_text) > OPT_W_LIMIT_NORM or count_chars(opt_text) > OPT_C_LIMIT_NORM:
            findings.append({
                "code": "E040_OPTION_LENGTH",
                "message": f"La opción '{opt.get('id', str(i))}' excede el límite de longitud ({OPT_W_LIMIT_NORM} palabras o {OPT_C_LIMIT_NORM} caracteres).",
                "field": f"opciones[{i}].texto"
            })

    # --- FIN NUEVAS VALIDACIONES DE ESTILO ---

    # Negaciones en minúscula (W101_STEM_NEG_LOWER)
    if any(f" {neg} " in stem_lower for neg in NEG_WORDS):
        findings.append({"code": "W101_STEM_NEG_LOWER", "message": "Negación en minúscula detectada en el enunciado.", "field": "enunciado_pregunta"})

    # Absolutos (W102_ABSOL_STEM)
    if any(f" {absol} " in stem_lower for absol in ABSOL_WORDS):
        findings.append({"code": "W102_ABSOL_STEM", "message": "Uso de absolutos en el enunciado.", "field": "enunciado_pregunta"})

    # Hedging (W103_HEDGE_STEM)
    if any(f" {hedge} " in stem_lower for hedge in HEDGE_WORDS):
        findings.append({"code": "W103_HEDGE_STEM", "message": "Expresión hedging innecesaria en el enunciado.", "field": "enunciado_pregunta"})

    # Cuantificadores vagos (W113_VAGUE_QUANTIFIER)
    vague = _check_quantifier_vagueness(stem_lower)
    if vague:
        findings.append({**vague, "field": "enunciado_pregunta"}) # Asegurarse de que el campo esté incluido

    # Frases prohibidas en opciones (E106_COMPLEX_OPTION_TYPE) - Ahora reclasificado a ERROR
    for i, opt in enumerate(options):
        opt_lower = opt.get("texto", "").lower()
        # Asegurarse de que el 'id' de la opción se usa correctamente en el field si existe
        option_field = f"opciones[{opt.get('id', str(i))}]" if opt.get('id') else f"opciones[{i}]"
        for f in FORBIDDEN_OPTIONS:
            if f in opt_lower:
                findings.append({
                    "code": "E106_COMPLEX_OPTION_TYPE",
                    "message": f"Frase prohibida ('{f}') detectada en la opción {opt.get('id', str(i))}.",
                    "field": f"{option_field}.texto"
                })
                break # Solo un finding por opción si se encuentra una frase prohibida

    # Homogeneidad de longitud entre opciones (W104_OPT_LEN_VAR)
    lengths_non_zero = [count_words(opt.get("texto", "")) for opt in options if opt.get("texto") and count_words(opt.get("texto", "")) > 0]
    if lengths_non_zero:
        min_len = min(lengths_non_zero)
        max_len = max(lengths_non_zero)
        # Umbral de 25% de diferencia: si la opción más larga es 1.25 veces (25%) más larga que la más corta
        if max_len > 0 and min_len > 0 and max_len / min_len > 1.25:
            findings.append({"code": "W104_OPT_LEN_VAR", "message": "Variación excesiva en la longitud de opciones.", "field": "opciones"})
    elif len(options) > 0 and all(not opt.get("texto").strip() for opt in options if opt.get("texto") is not None): # Todas las opciones están vacías o solo espacios
        findings.append({"code": "W104_OPT_LEN_VAR", "message": "Opciones con texto vacío o sin palabras detectado.", "field": "opciones"})


    # Pistas léxicas (W105_LEXICAL_CUE)
    correct_opt = next((o for o in options if o["id"] == correct_id), None)
    if correct_opt:
        # Asegurarse de que stem y correct_opt['texto'] no estén vacíos para evitar errores
        if stem_lower and correct_opt["texto"]:
            correct_tokens = set(re.findall(r"\b\w+\b", correct_opt["texto"].lower())) - STOP_WORDS
            stem_tokens = set(re.findall(r"\b\w+\b", stem_lower)) - STOP_WORDS # Usar stem_lower
            # Umbral: si hay al menos 2 palabras clave en común que no son stop words
            if len(correct_tokens.intersection(stem_tokens)) >= 2:
                findings.append({"code": "W105_LEXICAL_CUE", "message": "Pista léxica en la opción correcta.", "field": f"opciones[{correct_id}].texto"})


    # Similitud entre distractores (W112_DISTRACTOR_SIMILAR)
    sim_warn = _check_distractor_similarity(options)
    if sim_warn:
        findings.append({**sim_warn, "field": "opciones"}) # Asegurarse de que el campo esté incluido

    # Similitud entre stem y correcta (E091_CORRECTA_SIMILAR_STEM) - Ahora reclasificado a ERROR
    sim_corr = _check_stem_correct_similarity(item)
    if sim_corr:
        findings.append({**sim_corr, "field": "enunciado_pregunta"}) # Asegurarse de que el campo esté incluido

    # Validaciones de alt_text (W107_COLOR_ALT, W108_ALT_VAGUE)
    alt_text_issues = _check_alt_text(item)
    if alt_text_issues:
        for issue in alt_text_issues:
            findings.append({**issue, "field": "recurso_visual.alt_text"}) # Asegurarse de que el campo esté incluido

    # --- NUEVA VALIDACIÓN: W125_DESCRIPCION_DEFICIENTE ---
    # Verificar si la descripción del recurso visual es muy corta o está vacía
    if recurso_visual:
        description_text = recurso_visual.get("descripcion", "")
        # Considerar 'descripcion' vacía o menos de 10 palabras como deficiente
        if not description_text.strip() or count_words(description_text) < 10:
            findings.append({
                "code": "W125_DESCRIPCION_DEFICIENTE",
                "message": "La descripción del recurso visual es demasiado corta o está vacía.",
                "field": "recurso_visual.descripcion"
            })
    # --- FIN NUEVA VALIDACIÓN ---


    return findings
