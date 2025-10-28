-- Crear tabla
CREATE TABLE IF NOT EXISTS responses (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL UNIQUE,
    original_answer TEXT,
    llm_answer TEXT,
    score FLOAT,
    hit_count INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Crear índice
CREATE INDEX IF NOT EXISTS idx_question ON responses (question);
