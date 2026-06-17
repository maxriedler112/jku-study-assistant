-- RAG-Datenbankfunktionen fuer den JKU Study Assistant
-- ====================================================
-- Diese Datei dokumentiert die Postgres-Funktionen, die das Backend ueber
-- supabase.rpc(...) aufruft. In einem frischen Supabase-Projekt einmalig
-- ausfuehren (SQL Editor oder `supabase db push`), damit /chat und /programs
-- funktionieren.
--
-- Voraussetzungen (bereits vorhanden): pgvector-Extension sowie die Tabellen
-- study_programs(id uuid, code, name, degree_type),
-- documents(id uuid, study_program_id uuid, ...),
-- chunks(id uuid, document_id uuid, content text, embedding vector, metadata jsonb).


-- 1) Semantische Vektorsuche ueber alle Chunks, optional auf einen Studiengang
--    gefiltert. Wird von app/search.py (search_jku_knowledge) genutzt.
CREATE OR REPLACE FUNCTION public.match_documents(
    query_embedding   vector,
    match_threshold   double precision DEFAULT 0.3,
    match_count       integer          DEFAULT 10,
    filter_program_id uuid             DEFAULT NULL::uuid
)
RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
LANGUAGE sql
STABLE
AS $function$
    SELECT
        c.id,
        c.content,
        c.metadata,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE
        1 - (c.embedding <=> query_embedding) > match_threshold
        AND (filter_program_id IS NULL OR d.study_program_id = filter_program_id)
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$function$;


-- 2) Liefert alle Studiengaenge, die tatsaechlich Inhalte (chunks > 0) haben.
--    Wird von app/api.py (GET /programs) genutzt, damit das Frontend nur
--    befuellte Studiengaenge als Buttons anzeigt.
CREATE OR REPLACE FUNCTION public.list_study_programs_with_content()
RETURNS TABLE(id uuid, name text, degree_type text, chunk_count bigint)
LANGUAGE sql
STABLE
AS $function$
    SELECT sp.id, sp.name, sp.degree_type, COUNT(c.id) AS chunk_count
    FROM study_programs sp
    JOIN documents d ON d.study_program_id = sp.id
    JOIN chunks c ON c.document_id = d.id
    GROUP BY sp.id, sp.name, sp.degree_type
    HAVING COUNT(c.id) > 0
    ORDER BY sp.degree_type, sp.name;
$function$;
