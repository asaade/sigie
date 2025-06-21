-- init_tables.sql

-- 1. Habilitar la extensión para generación de UUIDs
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Crear la tabla 'items' con la estructura actualizada
CREATE TABLE IF NOT EXISTS items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temp_id UUID NOT NULL DEFAULT gen_random_uuid(), -- Añadido
    status VARCHAR(255) NOT NULL DEFAULT 'pending', -- Añadido
    payload JSONB NOT NULL,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    audits JSONB NOT NULL DEFAULT '[]'::jsonb, -- Añadido
    prompt_v TEXT,
    token_usage INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Índice GIN sobre JSONB para acelerar consultas filtrando por campos del payload
CREATE INDEX IF NOT EXISTS idx_items_payload
    ON items USING gin (payload);

-- 4. (Opcional) Índices GIN para errores y warnings, si se prevén consultas sobre ellos
-- CREATE INDEX IF NOT EXISTS idx_items_errors
--     ON items USING gin (errors);
-- CREATE INDEX IF NOT EXISTS idx_items_warnings
--     ON items USING gin (warnings);
