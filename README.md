# SIGIE – Sistema Inteligente de Generación de Ítems Educativos

## 📝 Descripción del Proyecto

**SIGIE** (Sistema Inteligente de Generación de Ítems Educativos) es una plataforma modular diseñada para la **generación y validación automatizada de ítems de opción múltiple (MCQ)** para evaluaciones educativas. Combina el poder de los **Modelos de Lenguaje Grandes (LLM)** con validaciones locales robustas para producir ítems de alta calidad, pedagógicamente válidos y estructuralmente correctos.

El sistema opera a través de un **pipeline secuencial** gestionado por un orquestador central, donde cada etapa es ejecutada por un agente (LLM o código local) con una responsabilidad específica. SIGIE está diseñado para ser extensible, desacoplado y completamente configurable.

## ✨ Características Principales

  * **Generación Automatizada:** Crea ítems de opción múltiple a partir de parámetros definidos (tema, nivel cognitivo, área, asignatura, etc.).
  * **Pipeline Modular por Etapas:** El proceso se divide en etapas secuenciales (generación, validación dura, validación lógica, refinamiento de estilo, validación de políticas, refinamiento de políticas, finalización y persistencia).
  * **Agentes LLM Especializados:** Cada etapa crítica es gestionada por un LLM (Agente de Dominio, Agente de Razonamiento, Agente Refinador de Lógica, Agente Refinador de Estilo, Agente de Políticas, Agente Refinador de Políticas, Agente Final) con prompts específicos.
  * **Validaciones Robustas:** Incluye validaciones estructurales (JSON Schema, Pydantic), validaciones lógicas (coherencia, precisión), y validaciones de políticas (sesgos, inclusión).
  * **Refinamiento Iterativo:** Los ítems que no cumplen con los criterios de validación son enviados a agentes refinadores para corrección automática, permitiendo ciclos de reintento controlados.
  * **Trazabilidad Completa:** Registra errores, advertencias, uso de tokens y un historial detallado de auditoría para cada ítem en cada etapa del pipeline.
  * **Soporte Multi-Proveedor LLM:** Configurable para usar diferentes proveedores LLM (OpenAI, OpenRouter, Google Gemini, Ollama) por etapa para optimizar rendimiento y costos.
  * **Persistencia de Datos:** Almacena ítems validados y sus metadatos en una base de datos PostgreSQL.

## 🚀 Arquitectura de Alto Nivel

El sistema se estructura en un pipeline (definido en `pipeline.yml`) ejecutado por un `runner.py` central.

```
+----------------+       +-------------------+       +--------------------+
| Solicitud API  | ----> | Runner (Orquestador) | ----> |  Etapa 1 (Generación) |
| (items_router) |       |   (pipeline.yml)   |       |      (LLM)         |
+----------------+       +-------------------+       +--------------------+
                                    |                           |
                                    v                           v
+-----------------------+   +-----------------------+   +-----------------------+
|  Etapa 2 (Val. Dura)  |-->|  Etapa 3 (Val. Lógica)|-->|  Etapa 4 (Ref. Lógica)|--> ...
|      (Local)          |   |      (LLM)            |   |      (LLM)            |
+-----------------------+   +-----------------------+   +-----------------------+
        |                               ^                         |
        |      Fallos críticos          |                         |
        +-------------------------------+                         |
                                                                  |
                                                                  v
                                                                  ... --> +-----------------------+
                                                                        |  Etapa N (Persistencia) |
                                                                        |       (Local)           |
                                                                        +-----------------------+
```

  * **`app/core/config.py`**: Gestión centralizada de la configuración.
  * **`app/llm/`**: Capa de abstracción para interactuar con diferentes proveedores LLM.
  * **`app/schemas/`**: Definiciones de la estructura de datos de ítems (Pydantic).
  * **`app/pipelines/`**: Contiene la lógica del orquestador (`runner.py`), el registro de etapas (`registry.py`), las implementaciones de cada etapa (`builtins/`), y utilidades (`utils/`).
  * **`app/prompts/`**: Almacena los prompts en Markdown para los Agentes LLM.
  * **`app/validators/`**: Contiene implementaciones de validaciones locales.
  * **`app/db/`**: Gestión de la base de datos (modelos ORM y sesión).

## 🛠️ Prerrequisitos

Antes de arrancar el sistema, asegúrate de tener instalados:

  * **Python 3.9+**
  * **pip** (gestor de paquetes de Python)
  * **Docker** y **Docker Compose** (para la base de datos PostgreSQL)
  * **Claves API** para los proveedores LLM que planees utilizar (OpenAI, Google, OpenRouter, u Ollama si lo ejecutas remotamente).

## 🚀 Configuración e Instalación

Sigue estos pasos para poner en marcha el sistema:

1.  **Clonar el Repositorio:**

    ```bash
    git clone https://github.com/asaade/sigie.git
    cd sigie
    ```

2.  **Crear y Activar un Entorno Virtual:**

    ```bash
    python3 -m venv venv
    source venv/bin/activate # En Linux/macOS
    # En Windows: .\venv\Scripts\activate
    ```

3.  **Instalar Dependencias de Python:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar Variables de Entorno (`.env`):**
    Crea un archivo llamado `.env` en la raíz de tu proyecto (al mismo nivel que `app/` y `pipeline.yml`). Copia el contenido siguiente y adapta los valores. **Es crucial que las credenciales de base de datos y las claves API sean correctas.**

    ```dotenv
    # .env
    # --- Configuración del Proveedor LLM por defecto ---
    LLM_PROVIDER="ollama" # O "openai", "openrouter", "gemini"
    LLM_MODEL="llama3.2"  # Modelo a usar por defecto para el proveedor seleccionado
    LLM_TEMPERATURE=0.7

    # --- OLLAMA (si LLM_PROVIDER es "ollama") ---
    OLLAMA_HOST=http://host.docker.internal:11434 # O la IP/puerto donde corre tu servidor Ollama

    # --- OpenAI (si LLM_PROVIDER es "openai" o "openrouter" en algunos modelos) ---
    # OPENAI_API_KEY="sk-YOUR_OPENAI_API_KEY"
    # OPENAI_BASE_URL="https://api.openai.com/v1" # O custom endpoint/proxy

    # --- OpenRouter (si LLM_PROVIDER es "openrouter") ---
    # OPENROUTER_API_KEY="sk-or-YOUR_OPENROUTER_API_KEY"
    # OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"

    # --- Gemini (si LLM_PROVIDER es "gemini") ---
    # GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"
    # GEMINI_BASE_URL="" # URL específica si es diferente a la default de Google

    # --- Control de Calidad / Resiliencia LLM ---
    LLM_MAX_RETRIES=3
    LLM_REQUEST_TIMEOUT=60.0

    # --- Configuración de Generación del Pipeline ---
    LLM_MAX_TOKENS=3000
    PROMPT_VERSION="2025-07-01"

    # --- Configuración de la Base de Datos PostgreSQL ---
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=postgres
    POSTGRES_DB=reactivos_db

    # Cadenas de conexión para la aplicación y para psql (usarán las variables de arriba)
    DATABASE_URL="postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@db:5432/$(POSTGRES_DB)"
    PSQL_DATABASE_URL="postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@db:5432/$(POSTGRES_DB)"
    ```

5.  **Configurar Docker Compose para PostgreSQL:**
    Asegúrate de tener un archivo `docker-compose.yaml` en la raíz de tu proyecto. Este archivo orquesta el servicio de base de datos.

    ```yaml
    # docker-compose.yaml
    version: '3.8'

    services:
      db:
        image: postgres:17-alpine
        container_name: sigie_postgres_db
        env_file:
          - .env # Carga variables POSTGRES_USER/PASSWORD/DB desde .env
        volumes:
          - db_data:/var/lib/postgresql/data
        ports:
          - "5432:5432"
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
          interval: 5s
          timeout: 5s
          retries: 5
          start_period: 10s

      web:
        build: .
        depends_on:
          db:
            condition: service_healthy # Espera a que el servicio 'db' esté sano
        env_file:
          - .env
        extra_hosts:
          - "host.docker.internal:host-gateway" # Para conectar con Ollama en el host desde Docker
        ports:
          - "8000:8000"
        volumes:
          - .:/usr/src/app # Montaje para desarrollo: cambios en código se reflejan sin reconstruir
        command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

    volumes:
      db_data:
    ```

6.  **Definir Esquema de Base de Datos (`migration.sql`):**
    Asegúrate de que este archivo esté en la raíz de tu proyecto. Es ejecutado por `entrypoint.sh` para crear las tablas.

    ```sql
    -- migration.sql
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";

    CREATE TABLE IF NOT EXISTS items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        temp_id UUID NOT NULL DEFAULT gen_random_uuid(),
        status VARCHAR(255) NOT NULL DEFAULT 'pending',
        payload JSONB NOT NULL,
        errors JSONB NOT NULL DEFAULT '[]'::jsonb,
        warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
        audits JSONB NOT NULL DEFAULT '[]'::jsonb,
        prompt_v TEXT,
        token_usage INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_items_payload
        ON items USING gin (payload);
    ```

7.  **Definir Script de Arranque de Contenedor (`entrypoint.sh`):**
    Este script se ejecuta cuando el contenedor `web` inicia, asegurando la DB y aplicando migraciones.

    ```bash
    #!/usr/bin/env sh
    set -e

    echo "⏳ Esperando a que Postgres esté disponible en $PSQL_DATABASE_URL ..."
    until psql "$PSQL_DATABASE_URL" -c '\q' 2>/dev/null; do
      printf '.'
      sleep 1
    done

    echo ""
    echo "✅ Postgres disponible. Ejecutando migraciones…"
    psql "$PSQL_DATABASE_URL" -f /usr/src/app/migration.sql

    echo "✅ Migraciones completadas. Iniciando Uvicorn…"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ```

8.  **Definir `Dockerfile`:**
    Este archivo construye la imagen Docker para tu aplicación web.

    ```dockerfile
    # Dockerfile
    FROM python:3.10-slim

    RUN apt-get update && \
        apt-get install -y --no-install-recommends postgresql-client && \
        rm -rf /var/lib/apt/lists/*

    WORKDIR /usr/src/app

    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt

    COPY . .
    RUN chmod +x /usr/src/app/entrypoint.sh

    EXPOSE 8000

    ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
    ```

## ▶️ Ejecución del Sistema

1.  **Arrancar la Base de Datos (PostgreSQL):**
    Abre una terminal en la raíz de tu proyecto y ejecuta:

    ```bash
    docker-compose up -d db
    ```

    Esto creará y arrancará el contenedor de PostgreSQL en segundo plano.

2.  **Arrancar la Aplicación FastAPI (en Docker):**
    Una vez que la base de datos esté lista, Docker Compose iniciará automáticamente el servicio `web`.

    ```bash
    docker-compose up web
    ```

    O si ya levantaste `db`, simplemente:

    ```bash
    docker-compose up -d web
    ```

    La aplicación FastAPI estará accesible en `http://localhost:8000`.

## 🧪 Prueba del Funcionamiento Básico

Puedes usar `curl` (o herramientas como Postman, Insomnia) para probar la API de generación de ítems.

**Ejemplo de Solicitud `POST /items/generate`:**

```bash
curl -X POST "http://localhost:8000/items/generate" \
-H "Content-Type: application/json" \
-d '{
  "cantidad": 1,
  "idioma_item": "es",
  "area": "Ciencias",
  "asignatura": "Biología",
  "tema": "Células eucariotas",
  "nivel_destinatario": "Media superior",
  "nivel_cognitivo": "comprender",
  "dificultad_prevista": "Media",
  "tipo_reactivo": "opción múltiple",
  "fragmento_contexto": null,
  "recurso_visual": null,
  "estimulo_compartido": null,
  "especificaciones_por_item": null
}'
```

**Respuesta Esperada (Ejemplo de Éxito):**

```json
{
  "success": true,
  "total_tokens_used": 500,
  "results": [
    {
      "item_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
      "status": "persisted",
      "payload": {
        "item_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
        "testlet_id": null,
        "estimulo_compartido": null,
        "metadata": {
          "idioma_item": "es",
          "area": "Ciencias",
          "asignatura": "Biología",
          "tema": "Células eucariotas",
          "contexto_regional": null,
          "nivel_destinatario": "Media superior",
          "nivel_cognitivo": "comprender",
          "dificultad_prevista": "Media",
          "fecha_creacion": "2025-06-21"
        },
        "tipo_reactivo": "opción múltiple",
        "fragmento_contexto": "Las células eucariotas son fundamentales para la vida compleja.",
        "recurso_visual": null,
        "enunciado_pregunta": "¿Cuál de las siguientes afirmaciones sobre las células eucariotas es correcta?",
        "opciones": [
          {
            "id": "a",
            "texto": "Carecen de núcleo definido.",
            "es_correcta": false,
            "justificacion": "Esa es una característica de las células procariotas."
          },
          {
            "id": "b",
            "texto": "Poseen orgánulos membranosos.",
            "es_correcta": true,
            "justificacion": "Los orgánulos como mitocondrias y retículo endoplasmático son distintivos de las eucariotas."
          },
          {
            "id": "c",
            "texto": "Su material genético se encuentra disperso en el citoplasma.",
            "es_correcta": false,
            "justificacion": "Esta es una característica de las células procariotas; en eucariotas, el ADN está en el núcleo."
          }
        ],
        "respuesta_correcta_id": "b"
      },
      "errors": [],
      "warnings": [],
      "audits": [
        {
          "stage": "generate",
          "timestamp": "2025-06-21T10:00:00.000000",
          "summary": "Ítem generado exitosamente por el Agente de Dominio (prompt: 01_agent_dominio.md).",
          "corrections": []
        },
        {
          "stage": "validate_hard",
          "timestamp": "2025-06-21T10:00:01.000000",
          "summary": "Validación dura: OK.",
          "corrections": []
        },
        {
          "stage": "validate_logic",
          "timestamp": "2025-06-21T10:00:02.000000",
          "summary": "Validación lógica: OK.",
          "corrections": []
        },
        {
          "stage": "validate_soft",
          "timestamp": "2025-06-21T10:00:03.000000",
          "summary": "Validación suave: OK. 0 advertencias detectadas.",
          "corrections": []
        },
        {
          "stage": "validate_policy",
          "timestamp": "2025-06-21T10:00:04.000000",
          "summary": "Validación de políticas: OK.",
          "corrections": []
        },
        {
          "stage": "finalize_item",
          "timestamp": "2025-06-21T10:00:05.000000",
          "summary": "Ítem finalizado y listo para persistir.",
          "corrections": []
        },
        {
          "stage": "persist",
          "timestamp": "2025-06-21T10:00:06.000000",
          "summary": "Ítem persistido exitosamente en DB con ID: f5e4d3c2-b1a0-9876-5432-10fedcba9876",
          "corrections": []
        }
      ],
      "token_usage": 350,
      "db_id": "f5e4d3c2-b1a0-9876-5432-10fedcba9876"
    }
  ]
}
```
