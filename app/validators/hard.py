# app/services/validators/hard.py
"""
Validadores duros divididos en dos fases:
- `structural_validate`: verifica esquema JSON, tipos, campos obligatorios,
  conteo de opciones y segmentación en completamiento.
- `constraints_validate`: comprueba límites de longitud y reglas de negocio.
"""
import os
import re
import uuid
import json
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError as JsonSchemaError
from app.core.constants import (
    STEM_W_LIMIT,
    STEM_C_LIMIT,
    OPT_W_LIMIT_NORM,
    OPT_C_LIMIT_NORM,
    OPT_W_LIMIT_EXT,
    OPT_C_LIMIT_EXT,
    FRAG_W_LIMIT,
    URL_PATTERN,
)

# Cargar el esquema JSON
dcurrent_dir = os.path.dirname(os.path.abspath(__file__))
schema_path = os.path.join(
    os.path.dirname(dcurrent_dir), "item_schema_v1.json"
)
with open(schema_path, "r", encoding="utf-8") as f:
    ITEM_SCHEMA = json.load(f)


def structural_validate(item: dict) -> list[dict]:
    """
    Valida la estructura básica y tipos del ítem:
    - Esquema JSON
    - UUIDs
    - Campos obligatorios (enunciado, opciones, metadata, tipo_reactivo)
    - Conteo de opciones (3-4)
    - Segmentación de completamiento
    """
    errors = []
    # 1. Validación contra esquema JSON
    try:
        jsonschema_validate(instance=item, schema=ITEM_SCHEMA)
    except JsonSchemaError as e:
        errors.append({
            "code": "E001",
            "message": f"Error de esquema JSON: {e.message} en {list(e.path)}",
        })
        return errors

    # 2. item_id válido
    item_id = item.get("item_id")
    if item_id:
        try:
            uuid.UUID(str(item_id), version=4)
        except ValueError:
            errors.append({"code": "E002", "message": "item_id no es un UUID v4 válido."})

    # 3. Campos obligatorios
    if not item.get("enunciado_pregunta"):
        errors.append({"code": "E003", "message": "enunciado_pregunta es obligatorio."})
    if not isinstance(item.get("opciones"), list):
        errors.append({"code": "E004", "message": "opciones debe ser una lista no nula."})

    # 4. Conteo de opciones
    opts = item.get("opciones", [])
    if not (3 <= len(opts) <= 4):
        errors.append({"code": "E009", "message": f"Debe haber 3-4 opciones, hay {len(opts)}."})

    # 5. segmentación en completamiento
    if item.get("tipo_reactivo") == "completamiento":
        holes = item.get("enunciado_pregunta", "").count("___")
        for opt in opts:
            segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.get("texto", ""))
            if len(segs) != holes:
                errors.append({"code": "E025", "message": f"Opc {opt.get('id')} tiene {len(segs)} segmentos vs {holes} huecos."})

    return errors


def constraints_validate(item: dict) -> list[dict]:
    """
    Valida límites y reglas de negocio:
    - Longitudes de enunciado y opciones
    - Unicidad y corrección de IDs
    - respuesta_correcta_id coherente
    - fragmento_contexto, recurso_visual y metadata.fecha_creacion
    """
    errors = []
    # 1. Conteo de palabras/caracteres en enunciado
    stem = item.get("enunciado_pregunta", "")
    words = len(re.findall(r"\b\w+\b", stem))
    if words > STEM_W_LIMIT:
        errors.append({"code":"E005","message":f"enunciado_pregunta excede {STEM_W_LIMIT} palabras ({words})."})
    if len(stem) > STEM_C_LIMIT:
        errors.append({"code":"E006","message":f"enunciado_pregunta excede {STEM_C_LIMIT} caracteres ({len(stem)})."})

    opts = item.get("opciones", [])
    # 2. Unicidad y corrección de IDs
    ids = []
    correct_opts = [o for o in opts if o.get("es_correcta")]
    for opt in opts:
        opt_id = opt.get("id")
        if not re.match(r"^[a-d]$", str(opt_id)):
            errors.append({"code":"E013","message":f"ID inválido: {opt_id}."})
        if opt_id in ids:
            errors.append({"code":"E014","message":f"ID duplicado: {opt_id}."})
        ids.append(opt_id)

    if len(correct_opts) != 1:
        errors.append({"code":"E010","message":f"Debe haber una opción correcta, hay {len(correct_opts)}."})
    rc = item.get("respuesta_correcta_id")
    if rc not in ids:
        errors.append({"code":"E018","message":f"respuesta_correcta_id '{rc}' no coincide con IDs."})

    # 3. Límites de cada opción
    for opt in opts:
        text = opt.get("texto", "")
        count = len(re.findall(r"\b\w+\b", text))
        if item.get("tipo_reactivo") in ["ordenamiento","relacion_elementos"]:
            max_w, max_c = OPT_W_LIMIT_EXT, OPT_C_LIMIT_EXT
        else:
            max_w, max_c = OPT_W_LIMIT_NORM, OPT_C_LIMIT_NORM
        if count > max_w:
            errors.append({"code":"E007","message":f"Opción {opt.get('id')} excede {max_w} palabras ({count})."})
        if len(text) > max_c:
            errors.append({"code":"E008","message":f"Opción {opt.get('id')} excede {max_c} caracteres ({len(text)})."})

    # 4. fragmento_contexto
    frag = item.get("fragmento_contexto")
    if frag:
        fw = len(re.findall(r"\b\w+\b", frag))
        if fw > FRAG_W_LIMIT:
            errors.append({"code":"E030","message":f"fragmento_contexto excede {FRAG_W_LIMIT} palabras ({fw})."})

    # 5. recurso_visual URL y longitudes
    rv = item.get("recurso_visual") or {}
    url = rv.get("referencia","")
    if url and not re.match(URL_PATTERN, url):
        errors.append({"code":"E036","message":f"URL inválida: {url}"})

    # 6. metadata fecha_creacion
    meta = item.get("metadata",{})
    fecha = meta.get("fecha_creacion","")
    if fecha and not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
        errors.append({"code":"E039","message":"metadata.fecha_creacion formato inválido."})

    return errors
