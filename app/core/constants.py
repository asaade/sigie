import re

# Límites de longitud
STEM_W_LIMIT = 60
STEM_C_LIMIT = 250

OPT_W_LIMIT_NORM = 30
OPT_C_LIMIT_NORM = 140
OPT_W_LIMIT_EXT = 35  # ordenamiento / relacion_elementos
OPT_C_LIMIT_EXT = 180

FRAG_W_LIMIT = 100

# Palabras para validación
STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "ante",
    "bajo", "con", "contra", "desde", "durante", "en", "entre", "hacia", "hasta", "mediante",
    "para", "por", "segun", "sin", "sobre", "tras", "versus", "via", "y", "o", "u", "ni", "–"
}
NEG_WORDS = ["no", "nunca", "jamás", "ningún", "ninguna", "ninguno", "nadie", "nada"]
ABSOL_WORDS = ["siempre", "nunca", "todo", "todos", "nada", "nadie", "ninguno", "absolutamente"]
DESCRIPTIVE_VERBS = ["muestra", "indica", "representa", "describe", "ilustra", "contiene", "detalla", "explica",
                     "compara", "presenta", "resume", "provee", "visualiza"]
HEDGE_WORDS = ["aproximadamente", "quizá", "quizás", "posiblemente", "probablemente", "casi", "podría", "suele"]
FORBIDDEN_OPTIONS = ["todas las anteriores", "ninguna de las anteriores"]
COLOR_WORDS = ["rojo", "verde", "azul", "amarillo", "negro", "blanco", "gris", "naranja", "morado", "rosa", "marrón"]

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
