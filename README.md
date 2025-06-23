# SIGIE – Sistema Inteligente de Generación de Ítems Educativos

## 📝 Descripción del Proyecto

**SIGIE** (Sistema Inteligente de Generación de Ítems Educativos) es una plataforma modular diseñada para la **generación y validación automatizada de ítems de opción múltiple (MCQ)** para evaluaciones educativas. Combina el poder de los **Modelos de Lenguaje Grandes (LLM)** con validaciones programáticas robustas para producir ítems de alta calidad, pedagógicamente válidos y estructuralmente correctos.

El sistema opera a través de un **pipeline secuencial y lineal**, donde cada etapa es una clase autocontenida y especializada que se encarga de una única responsabilidad, garantizando un diseño limpio, extensible y fácil de mantener.

## ✨ Características Principales

  * **Generación Automatizada:** Crea ítems de opción múltiple a partir de parámetros definidos (tema, nivel cognitivo, área, etc.).
  * **Pipeline Lineal y Predecible:** El proceso se divide en etapas secuenciales definidas explícitamente en `pipeline.yml`. Su flujo, sin saltos condicionales complejos, hace que la ejecución sea fácil de seguir y depurar.
  * **Arquitectura de Clases Extensible:** Cada etapa del pipeline es una clase que hereda de una abstracción base (`BaseStage`/`LLMStage`). Esta arquitectura elimina el código repetitivo y hace que añadir nuevas etapas sea un proceso rápido y estandarizado.
  * **Resiliencia Pragmática (Fail-Fast):** Un ítem que no supera una validación crítica es marcado como fallido (`.fail`) y las etapas posteriores lo omiten, optimizando recursos, a menos que una etapa esté diseñada para actuar sobre ese fallo específico.
  * **Soporte Multi-Proveedor LLM:** Es configurable para usar diferentes proveedores (OpenAI, Gemini, etc.) y modelos por cada etapa, permitiendo optimizar costos y calidad.
  * **Trazabilidad Completa:** Registra todos los hallazgos (`findings`) y un historial de auditoría detallado (`audits`) para cada ítem en cada etapa del pipeline.
  * **Persistencia con Capa de Servicio:** Almacena los ítems procesados en una base de datos PostgreSQL a través de una capa de servicio (`crud.py`) que abstrae las operaciones de base de datos.

## 🚀 Arquitectura de Alto Nivel

El sistema se estructura en un pipeline (definido en `pipeline.yml`) ejecutado por un `runner.py` central. El `runner` lee el pipeline y, para cada etapa, instancia y ejecuta la clase correspondiente.

  * **`app/api/items_router.py`**: Define el endpoint de FastAPI y maneja las solicitudes y respuestas HTTP.
  * **`app/pipelines/runner.py`**: El orquestador lineal. Itera sobre `pipeline.yml`, instancia las clases de etapa y ejecuta su método `.execute()`.
  * **`app/pipelines/abstractions.py`**: **Archivo clave de la arquitectura.** Contiene las clases base `BaseStage` y `LLMStage`.
  * **`app/pipelines/builtins/`**: Contiene las implementaciones de cada etapa como clases dedicadas.
  * **`app/llm/`**: Capa de servicio aislada para interactuar con diferentes proveedores LLM.
  * **`app/db/`**: Gestión de la base de datos, incluyendo modelos de SQLAlchemy y la capa de servicio `crud`.
  * **`app/schemas/`**: Definiciones de los modelos de datos Pydantic.
  * **`app/prompts/`**: Almacena los prompts en Markdown para los Agentes LLM.

## 📋 Funcionamiento del Pipeline

### Etapas del Flujo de Trabajo

El flujo se define en `pipeline.yml` y típicamente incluye: `generate_items`, `validate_hard`, `validate_logic`, `refine_item_logic`, `correct_item_style`, `validate_policy`, `refine_item_policy`, `validate_soft`, `finalize_item` y `persist`.

### Flujo Condicional con `listen_to_status`

El parámetro `listen_to_status` en `pipeline.yml` sirve para que una etapa se ejecute de manera **condicional**, procesando únicamente los ítems que tienen un estado específico. Su propósito es crear ciclos de **validación y refinamiento eficientes**.

**Ejemplo:**

```yaml
  - name: validate_logic
    params:
      prompt: "02_agent_razonamiento.md"

  - name: refine_item_logic
    params:
      prompt: "03_agente_refinador_razonamiento.md"
      listen_to_status: "validate_logic.fail"
```

1.  La etapa `validate_logic` se ejecuta. Si un ítem falla, su estado se actualiza a `"validate_logic.fail"`.
2.  La siguiente etapa, `refine_item_logic`, gracias al parámetro `listen_to_status`, **filtrará y solo procesará los ítems cuyo estado sea `"validate_logic.fail"`**. Los ítems que pasaron la validación son ignorados por esta etapa, ahorrando recursos.

### Catálogo de Estados (Status)

El `status` de un ítem sigue la convención `nombre_de_etapa.resultado`. Un `.fail` detiene el procesamiento, a menos que una etapa posterior escuche ese estado.

  * **`generate_items`**: `.success` o `.fail` (por error del LLM o de parseo).
  * **`validate_hard`**: `.success` o `.fail` (por fallo en reglas programáticas).
  * **`validate_logic`**: `.success` o `.fail` (por fallo lógico detectado por el LLM).
  * **`refine_item_logic`**: `.success` (el resto de fallos son de sistema, ej: `.fail.id_mismatch`).
  * **`correct_item_style`**: `.success`.
  * **`validate_policy`**: `.success` o `.fail` (por advertencias de políticas).
  * **`refine_item_policy`**: `.success`.
  * **`validate_soft`**: No genera `status`, solo añade `findings` de tipo `warning`.
  * **`finalize_item`**: `.success` (publicable) o `.fail` (no publicable).
  * **`persist`**: `.success` o `.fail`.

## 🛠️ Prerrequisitos, Instalación y Uso

*(Esta sección se mantiene como en la versión anterior del README, ya que es correcta y detallada. Incluye los pasos para clonar, instalar dependencias, configurar `.env` y usar Docker.)*

## 🧪 Uso de la API (Ejemplo)

**Solicitud `POST /items/generate`:**

```bash
curl -X POST "http://localhost:8000/items/generate" \
-H "Content-Type: application/json" \
-d '{
  "n_items": 2,
  "area": "Ciencias",
  "tema": "Leyes de Newton"
}'
```

### **Respuesta Esperada**

La API devolverá un objeto `GenerationResponse` con el resultado de cada ítem. Los `errors` y `warnings` previos se unifican en la lista `findings`.

#### **Caso 1: Ítem exitoso**

```json
{
  "success": true,
  "total_tokens_used": 2150,
  "results": [
    {
      "item_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
      "status": "persist.success",
      "payload": { "... Contenido del ítem ..." },
      "findings": [],
      "audits": [ ... ],
      "final_evaluation": { "is_publishable": true, "score": 8.5, ... },
      "token_usage": 1200
    }
  ]
}
```

#### **Caso 2: Ítem con Fallo de Lógica**

```json
{
  "success": false,
  "total_tokens_used": 950,
  "results": [
    {
      "item_id": "b2c3d4e5-f6a7-8901-2345-67890abcdef1",
      "status": "validate_logic.fail",
      "payload": { "... Contenido hasta el fallo ..." },
      "findings": [
        {
          "code": "E073",
          "message": "La justificación contradice el enunciado.",
          "field": "opciones[0].justificacion",
          "severity": "error"
        }
      ],
      "audits": [ ... ],
      "final_evaluation": null,
      "token_usage": 500
    }
  ]
}
```

## 🔧 Mantenimiento y Extensión

Para añadir una nueva etapa:

1.  **Crear la Clase:** En `app/pipelines/builtins/`, crea un archivo para tu clase, que debe heredar de `BaseStage` o `LLMStage`.
2.  **Implementar la Lógica:** Completa los métodos abstractos requeridos.
3.  **Registrar la Etapa:** Usa el decorador `@register("nombre_de_tu_etapa")` en la clase.
4.  **Añadir al Pipeline:** Agrega la etapa y sus `params` al archivo `pipeline.yml`.
