# **SIGIE: Sistema Inteligente de Generación de Ítems Educativos**

**Versión Alpha 1.0**

## **Descripción General**

**SIGIE** es un sistema avanzado para la generación automática de reactivos o ítems de evaluación utilizando Inteligencia Artificial. A través de una pipeline de procesamiento configurable, SIGIE es capaz de crear, validar, refinar y evaluar ítems de alta calidad, asegurando su validez psicométrica, coherencia pedagógica y alineación con políticas de equidad.
Este proyecto está diseñado para ser una herramienta robusta y flexible para instituciones educativas, agencias de evaluación y desarrolladores de contenido que buscan escalar su producción de materiales de evaluación de manera eficiente y controlada.

## **✨ Características Principales**

* **Pipeline de Generación por Etapas:** El núcleo del sistema es una pipeline secuencial y configurable (pipeline.yml) que procesa los ítems en etapas discretas, desde la creación inicial hasta la evaluación final.
* **Agentes de IA Especializados:** Cada etapa es manejada por un "agente" de IA (impulsado por un LLM) con un rol y un prompt específico, permitiendo una alta especialización en tareas como validación lógica, refinamiento de contenido, revisión de estilo, etc.
* **Soporte para Contenido Gráfico:** Capacidad para generar y procesar ítems que incluyen recursos gráficos como tablas (Markdown), fórmulas matemáticas (LaTeX) y prompts para la generación de imágenes (SVG, etc.).
* **Configuración Declarativa:** El flujo de trabajo y el comportamiento de los agentes de IA se definen en archivos de configuración (.yml) y prompts (.md), permitiendo ajustes rápidos sin modificar el código fuente.
* **API Asíncrona:** Expone una API RESTful (basada en FastAPI) que maneja las solicitudes de generación de forma asíncrona, permitiendo procesar grandes lotes de ítems sin bloquear al cliente.
* **Validación Rigurosa:** Incluye múltiples capas de validación, tanto programáticas (validate\_hard, validate\_soft) como basadas en IA, para garantizar la calidad y coherencia de cada ítem.

## **🚀 Inicio Rápido (Getting Started)**

### **Requisitos Previos**

* Python 3.10+
* Docker y Docker Compose (recomendado para un despliegue sencillo)
* curl o un cliente de API como Postman.

### **Instalación y Ejecución**

1. **Clona el repositorio:**
   git clone \[URL-DEL-REPOSITORIO\]
   cd \[NOMBRE-DEL-DIRECTORIO\]

2. Configura las variables de entorno:
   Crea un archivo .env en la raíz del proyecto y añade tus claves de API y la configuración de la base de datos. Basado en env.example:
   \# Ejemplo de .env
   DATABASE\_URL="postgresql://user:password@db:5432/sigie\_db"
   GOOGLE\_API\_KEY="tu\_api\_key\_de\_google\_aqui"
   \# ... otras variables

3. **Levanta los servicios con Docker:**
   docker-compose up \--build

   Esto iniciará la aplicación FastAPI, la base de datos PostgreSQL y cualquier otro servicio necesario. La API estará disponible en http://localhost:8000.

## **⚙️ Uso Básico**

Para generar tu primer ítem, puedes usar el siguiente comando curl.

1. **Crea un archivo payload.json:**

```json
{
       "n\_items": 1,
       "dominio": {
           "area": "Ciencias Exactas",
           "asignatura": "Física",
           "tema": "Leyes de Newton"
       },
       "objetivo\_aprendizaje": "Aplicar la Segunda Ley de Newton (F=ma) para calcular la aceleración de un objeto con masa y fuerza conocidas.",
       "audiencia": {
           "nivel\_educativo": "Bachillerato (1er año)",
           "dificultad\_esperada": "media"
       },
       "nivel\_cognitivo": "Aplicar"
   }
```

2. **Envía la solicitud a la API:**
   curl \-X POST "http://localhost:8000/api/v1/items/generate" \\
   \-H "Content-Type: application/json" \\
   \--data-binary "@payload.json"

3. **Recibirás una respuesta 202 Accepted** confirmando que el proceso ha comenzado en segundo plano.

## **📂 Estructura del Proyecto**


```ascii
├── app/
│   ├── api/          \# Endpoints de FastAPI y routers
│   ├── core/         \# Configuración, catálogos de errores
│   ├── db/           \# Modelos SQLAlchemy, sesión de DB, CRUD
│   ├── llm/          \# Clientes de proveedores de LLM (Gemini, OpenAI)
│   ├── pipelines/
│   │   ├── builtins/ \# Implementaciones de cada etapa (Python)
│   │   ├── utils/    \# Funciones de ayuda para la pipeline
│   │   ├── abstractions.py \# Clases base (BaseStage, LLMStage)
│   │   ├── registry.py     \# Registro de etapas
│   │   └── runner.py       \# Orquestador de la pipeline
│   ├── prompts/      \# Archivos .md con los prompts de cada agente
│   └── schemas/      \# Modelos Pydantic para validación de datos
├── tests/            \# Pruebas unitarias y de integración
├── pipeline.yml      \# Archivo de configuración principal de la pipeline
└── ...
```

## **🛠️ Configuración y Personalización**

* **Para cambiar el flujo de generación:** Modifica el archivo pipeline.yml. Puedes reordenar, añadir o eliminar etapas para crear diferentes flujos de trabajo.
* **Para cambiar el comportamiento de la IA:** Edita los archivos .md correspondientes en el directorio app/prompts/. Cada archivo controla un agente de IA específico.

¡Gracias por usar SIGIE\!
