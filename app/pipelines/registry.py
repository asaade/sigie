# app/pipelines/registry.py

from collections import OrderedDict
from typing import Dict, Type
import importlib
import pkgutil
import logging

# Se importa la clase base real para un tipado correcto y consistente.
from app.pipelines.abstractions import BaseStage

logger = logging.getLogger(__name__)

_REGISTRY: Dict[str, Type[BaseStage]] = OrderedDict()
_BUILTINS_LOADED = False

def register(name: str):
    """Decorador para registrar una clase de etapa del pipeline."""
    def decorator(cls: Type[BaseStage]):
        if name in _REGISTRY:
            logger.warning(f"Stage '{name}' is being re-registered.")
        _REGISTRY[name] = cls
        return cls
    return decorator

def _load_builtin_stages() -> None:
    """
    Importa dinámicamente todos los módulos dentro de app.pipelines.builtins
    para activar sus decoradores @register. Se ejecuta solo una vez.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    try:
        package = importlib.import_module("app.pipelines.builtins")
        logger.debug(f"Auto-loading stages from: {package.__path__}")
        for _, mod_name, _ in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package.__name__}.{mod_name}")
    except Exception as e:
        logger.error(f"Could not auto-load built-in stages: {e}", exc_info=True)

    _BUILTINS_LOADED = True

def get_stage_by_name(name: str) -> Type[BaseStage]:
    """
    Obtiene una clase de etapa por su nombre, asegurando que los built-ins
    estén cargados.
    """
    _load_builtin_stages()
    if name not in _REGISTRY:
        raise KeyError(f"Stage '{name}' not found in registry. Available stages: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]

def get_full_registry() -> Dict[str, Type[BaseStage]]:
    """
    Devuelve el diccionario completo del registro, asegurando que los
    built-ins estén cargados.
    """
    _load_builtin_stages()
    return _REGISTRY.copy()
