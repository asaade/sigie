-- migration.sql

-- Habilitar la extensión para generación de UUIDs si no existe
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Crear o actualizar la tabla 'items' con la estructura final
CREATE TABLE IF NOT EXISTS items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temp_id UUID NOT NULL,
    status VARCHAR(255) NOT NULL,
    payload JSONB,
    -- La lista unificada de hallazgos (errores y advertencias)
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    audits JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_v TEXT,
    token_usage INTEGER,
    final_evaluation JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- (Opcional) Trigger para actualizar 'updated_at' automáticamente
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER set_timestamp
BEFORE UPDATE ON items
FOR EACH ROW
EXECUTE PROCEDURE trigger_set_timestamp();

CREATE EXTENSION IF NOT EXISTS pg_trgm; -- Asegurarse de que la extensión pg_trgm esté habilitada

-- Crear índice GIN sobre el payload para acelerar búsquedas
CREATE INDEX IF NOT EXISTS idx_items_payload ON items USING gin (payload);

-- Crear índice GIN sobre los findings
CREATE INDEX IF NOT EXISTS idx_items_findings ON items USING gin (findings);

-- INICIAR MODIFICACIONES PARA FILTRADO ESPECÍFICO

-- Crear índices GIN para campos frecuentemente usados en filtros dentro de 'payload' -> 'metadata'
-- El operador '->>' extrae el valor como texto, ideal para comparaciones de igualdad.

-- Índice para 'area' (ej. 'Matemáticas', 'Ciencias')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_area ON items USING gin ((payload -> 'metadata' ->> 'area') gin_trgm_ops);

-- Índice para 'asignatura' (ej. 'Álgebra', 'Física')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_asignatura ON items USING gin ((payload -> 'metadata' ->> 'asignatura') gin_trgm_ops);

-- Índice para 'nivel_destinatario' (ej. 'Media superior', 'Secundaria')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_nivel_destinatario ON items USING gin ((payload -> 'metadata' ->> 'nivel_destinatario') gin_trgm_ops);

-- Índice para 'tema' (ej. 'Ecuaciones', 'Leyes de Newton')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_tema ON items USING gin ((payload -> 'metadata' ->> 'tema') gin_trgm_ops);

-- Índice para 'nivel_cognitivo' (ej. 'aplicar', 'analizar')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_nivel_cognitivo ON items USING gin ((payload -> 'metadata' ->> 'nivel_cognitivo') gin_trgm_ops);

-- Índice para 'dificultad_prevista' (ej. 'media', 'dificil')
CREATE INDEX IF NOT EXISTS idx_payload_metadata_dificultad_prevista ON items USING gin ((payload -> 'metadata' ->> 'dificultad_prevista') gin_trgm_ops);

-- Índice para 'tipo_reactivo' (ej. 'cuestionamiento_directo', 'completamiento')
-- Nota: 'tipo_reactivo' está directamente bajo 'payload', no bajo 'metadata'.
CREATE INDEX IF NOT EXISTS idx_payload_tipo_reactivo ON items USING gin ((payload ->> 'tipo_reactivo') gin_trgm_ops);


-- Ejemplo

-- SELECT
--     id,
--     status,
--     payload -> 'metadata' ->> 'area' AS area,
--     payload -> 'metadata' ->> 'asignatura' AS asignatura,
--     payload -> 'metadata' ->> 'nivel_destinatario' AS nivel_destinatario,
--     payload -> 'metadata' ->> 'tema' AS tema,
--     payload -> 'metadata' ->> 'nivel_cognitivo' AS nivel_cognitivo,
--     payload -> 'metadata' ->> 'dificultad_prevista' AS dificultad_prevista,
--     payload ->> 'tipo_reactivo' AS tipo_reactivo
-- FROM
--     items
-- WHERE
--     (payload -> 'metadata' ->> 'area') = 'Ciencias' AND
--     (payload -> 'metadata' ->> 'asignatura') = 'Matemáticas' AND
--     (payload -> 'metadata' ->> 'nivel_destinatario') = 'Media superior';
