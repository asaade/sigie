
Estoy desarrollando un sistema modular que automatiza la generación y validación de ítems de opción múltiple para evaluación educativa. El flujo se organiza en etapas secuenciales, donde cada una está a cargo de un agente (modelo LLM) con una responsabilidad específica. El sistema está diseñado para ser extensible y desacoplado, y se basa en un orquestador central que gestiona el paso de datos entre agentes.

### 🔧 Funcionalidad general del sistema

El sistema genera ítems con parámetros definidos (tema, nivel cognitivo, etc.), valida aspectos estructurales y de contenido, y aplica correcciones automáticas. El flujo incluye generación, validación, refinamiento, evaluación final y persistencia.

### 🧱 Estructura del código

* **`runner.py`**: archivo principal. Ejecuta el flujo completo, invocando módulos en el orden definido en `flow.yaml`. Maneja el paso de datos y el estado entre etapas.

* **`stages.py`**: lista los nombres de todas las etapas disponibles. Cada etapa corresponde a una función decorada registrada en `registry.py`.

* **`registry.py`**: decorador `@register()` que asocia un nombre de etapa a una función de Python. Esto permite que el orquestador invoque dinámicamente la función correspondiente a cada etapa del flujo.

* **`flow.yaml`**: define la secuencia de etapas (prompts y módulos) del flujo de generación/validación. Es el plan maestro que sigue `runner.py`.

* **Módulos por etapa**:

  * `generate_items.py`: genera ítems nuevos.
  * `refine_item_style.py`, `refine_item_logic.py`, `refine_item_policy.py`: refinan ítems según criterios específicos.
  * `hard_validate.py`, `soft_validate.py`: validadores tradicionales (no LLM).
  * `finalize_item.py`: emite una evaluación final del ítem sin modificarlo.
  * `persist.py`: guarda ítems en la base de datos o sistema de archivos.

* **`app/schemas/item_schemas.py`**: define la estructura y validación formal del ítem usando Pydantic.

* **`app/llm.py`**: interfaz con el modelo LLM (por ejemplo, OpenAI), usada para enviar prompts y recibir respuestas.

* **`app/prompts/`**: contiene los archivos `.md` con los prompts en lenguaje natural que se cargan para cada etapa.

### 📌 Objetivo de esta sesión

Quiero continuar con la revisión y refactorización de los módulos del sistema, asegurando que:

* Cada módulo esté alineado con los prompts de LLM propios de cada módulo.
* Manejen adecuadamente errores, validaciones y estructura del ítem.
* El flujo de información sea coherente entre etapas.
* No haya redundancias innecesarias o ambigüedades.

Podemos comenzar el orden que tú recomiendes priorizar. Pídeme cualquier archivo que necesites.
