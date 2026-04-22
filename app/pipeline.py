import io
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from chunking import chunk_text
from embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise ValueError("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt in der .env Datei")

supabase: Client = create_client(url, key)

BUCKET = "documents"


def get_or_create_study_program(code: str, name: str) -> str:
    """Gibt die ID eines Studiengangs zurück, legt ihn an falls er noch nicht existiert."""
    result = supabase.table("study_programs").select("id").eq("code", code).execute()
    if result.data:
        return result.data[0]["id"]
    insert = supabase.table("study_programs").insert({"code": code, "name": name}).execute()
    return insert.data[0]["id"]


def document_exists(filename: str, study_program_id: str) -> bool:
    """Prüft ob ein Dokument mit diesem Namen bereits für den Studiengang existiert."""
    result = (
        supabase.table("documents")
        .select("id")
        .eq("filename", filename)
        .eq("study_program_id", study_program_id)
        .execute()
    )
    return len(result.data) > 0


def process_pdf(pdf_bytes: bytes, filename: str, study_program_id: str) -> int:
    """Kompletter Flow: PDF-Bytes → Storage → Chunks → Embeddings → Supabase.
    Gibt die Anzahl der erstellten Chunks zurück.
    Wirft ValueError wenn das Dokument bereits existiert.
    """
    import pdfplumber

    # Duplikat-Check
    if document_exists(filename, study_program_id):
        raise ValueError(f"'{filename}' wurde für diesen Studiengang bereits hochgeladen.")

    # Studienkennzahl für den Storage-Pfad holen
    program = supabase.table("study_programs").select("code").eq("id", study_program_id).execute()
    program_code = program.data[0]["code"].replace("/", "-") if program.data else "allgemein"
    bucket_path = f"{program_code}/{filename}"

    # 1. PDF in Storage hochladen
    supabase.storage.from_(BUCKET).upload(
        bucket_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    # 2. Dokument-Eintrag anlegen
    doc_result = supabase.table("documents").insert({
        "filename":         filename,
        "bucket_path":      bucket_path,
        "study_program_id": study_program_id,
        "status":           "processing",
    }).execute()
    document_id = doc_result.data[0]["id"]

    try:
        # 3. Text aus PDF-Bytes extrahieren
        full_text = ""
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if not page_text:
                    continue
                if page_text.count(". .") > 8:
                    continue
                full_text += page_text + "\n"

        # 4. Chunken + Embeddings
        chunks = chunk_text(full_text)
        embed_service = EmbeddingService()
        embeddings = embed_service.embed_texts(chunks)

        # 5. Chunks speichern
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk,
                "embedding":   vector,
                "chunk_index": i,
                "metadata":    {"source": filename, "chunk_index": i},
            }).execute()

        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks)


def process_ics(ics_bytes: bytes, filename: str, user_id: str) -> int:
    """ICS-Bytes parsen und Events für den User in Supabase speichern."""
    import tempfile
    from ingest_ics import ingest_ics

    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        tmp.write(ics_bytes)
        tmp_path = tmp.name

    try:
        ingest_ics(tmp_path, user_id)
    finally:
        os.unlink(tmp_path)

    result = supabase.table("events").select("id", count="exact").eq("user_id", user_id).execute()
    return result.count or 0
