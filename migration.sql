-- migration.sql

DROP TABLE IF EXISTS items CASCADE;

-- Habilitar la extensión para generación de UUIDs si no existe
CREATE EXTENSION IF NOT NOT EXISTS "pgcrypto";

-- Crear o actualizar la tabla 'items' con la estructura final
CREATE TABLE IF NOT EXISTS items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temp_id UUID NOT NULL,
    batch_id VARCHAR(255) NOT NULL,
    status VARCHAR(255) NOT NULL,
    payload JSONB,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    audits JSONB NOT NULL DEFAULT '[]'::jsonb,
    change_log JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_v TEXT,
    token_usage INTEGER,
    final_evaluation JSONB NOT NULL DEFAULT '[]'::jsonb,
    generation_params JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigger para actualizar 'updated_at' automáticamente
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

-- Habilitar extensión para índices GIN en texto
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- --- ÍNDICES ---

-- Índice para búsquedas por lote
CREATE INDEX IF NOT EXISTS idx_items_batch_id ON items (batch_id);

-- Índices GIN para campos JSONB
CREATE INDEX IF NOT EXISTS idx_items_payload ON items USING gin (payload);
CREATE INDEX IF NOT EXISTS idx_items_findings ON items USING gin (findings);
CREATE INDEX IF NOT EXISTS idx_items_change_log ON items USING gin (change_log);

-- Índices para filtros específicos dentro del payload
CREATE INDEX IF NOT EXISTS idx_payload_metadata_area ON items USING gin ((payload -> 'metadata' ->> 'area') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_metadata_asignatura ON items USING gin ((payload -> 'metadata' ->> 'asignatura') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_metadata_nivel_destinatario ON items USING gin ((payload -> 'metadata' ->> 'nivel_destinatario') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_metadata_tema ON items USING gin ((payload -> 'metadata' ->> 'tema') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_metadata_nivel_cognitivo ON items USING gin ((payload -> 'metadata' ->> 'nivel_cognitivo') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_metadata_dificultad_prevista ON items USING gin ((payload -> 'metadata' ->> 'dificultad_prevista') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_payload_tipo_reactivo ON items USING gin ((payload ->> 'tipo_reactivo') gin_trgm_ops);
