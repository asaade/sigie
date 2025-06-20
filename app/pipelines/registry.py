# app/pipelines/registry.py
from collections import OrderedDict
from typing import Dict, Protocol
import importlib
import pkgutil

_REGISTRY: Dict[str, "Stage"] = OrderedDict()
_BUILTINS_LOADED = False  # flag global

# ─── Stage protocolo (mantenemos) ───────────────────────────────────────────
class Stage(Protocol):
    name: str
    async def __call__(self, items, ctx): ...

# ─── Decorador register (sin cambios) ───────────────────────────────────────
def register(name: str):
    def decorator(stage_callable: Stage):
        if name in _REGISTRY:
            raise ValueError(f"Stage name duplicated: {name!r}")
        stage_callable.name = name           # type: ignore[attr-defined]
        _REGISTRY[name] = stage_callable
        return stage_callable
    return decorator

# ─── Auto-loader de builtins ────────────────────────────────────────────────
def _load_builtin_stages() -> None:
    """Importa todos los módulos dentro de app.pipelines.builtins una vez."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    package = importlib.import_module("app.pipelines.builtins")
    for _, mod_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{mod_name}")
    _BUILTINS_LOADED = True

def get(name: str) -> Stage:
    _load_builtin_stages()        # <-- asegura que el registro esté poblado
    return _REGISTRY[name]

def all() -> Dict[str, Stage]:
    _load_builtin_stages()
    return _REGISTRY.copy()
