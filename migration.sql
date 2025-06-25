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


-- Crear índice GIN sobre el payload para acelerar búsquedas
CREATE INDEX IF NOT EXISTS idx_items_payload ON items USING gin (payload);

-- Crear índice GIN sobre los findings
CREATE INDEX IF NOT EXISTS idx_items_findings ON items USING gin (findings);
