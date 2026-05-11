"""
pipeline.py – Zentrale ETL-Pipeline des JKU Study Assistants.

Ablauf:
  PDF-Bytes  →  Supabase Storage
             →  Seitenweise Text- & Tabellen-Extraktion (pdfplumber)
             →  Chunking (chunking.py)
             →  Embeddings (embeddings.py / E5-Modell)
             →  Chunks + Metadaten in Supabase speichern

ICS-Bytes   →  Kalender-Events parsen  →  Supabase (ingest_ics.py)
"""

import io
import re
import os
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from chunking import chunk_text
from embeddings import EmbeddingService

# ── Umgebungsvariablen laden (.env Datei) ────────────────────────────────────
load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise ValueError("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt in der .env Datei")

# Supabase-Client mit Service-Role-Key (umgeht RLS für Server-seitige Operationen)
supabase: Client = create_client(url, key)

# Name des Supabase-Storage-Buckets für PDF-Dateien
BUCKET = "documents"


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def table_to_markdown(table: list) -> str:
    """
    Wandelt eine pdfplumber-Tabelle (Liste von Zeilen, jede Zeile = Liste von Zellen)
    in einen Markdown-Tabellenstring um.

    Beispiel Eingabe:  [["Fach", "ECTS"], ["Mathematik", "4"]]
    Beispiel Ausgabe:  | Fach | ECTS |
                       | --- | --- |
                       | Mathematik | 4 |
    """
    if not table or not table[0]:
        return ""

    rows = []
    for row in table:
        # Zellen bereinigen: None → "", interne Umbrüche entfernen, Whitespace trimmen
        cells = [str(cell or "").replace("\n", " ").strip() for cell in row]
        rows.append("| " + " | ".join(cells) + " |")

    if not rows:
        return ""

    # Trennzeile zwischen Header (Zeile 0) und Daten einfügen
    separator = "| " + " | ".join(["---"] * len(table[0])) + " |"
    rows.insert(1, separator)

    return "\n".join(rows)


def extract_section_heading(text: str) -> Optional[str]:
    """
    Versucht, die erste Abschnittsüberschrift im Rohtext einer Seite zu erkennen.

    Erkannte Muster:
      - Paragraphen-Nummern: "§ 1 Allgemeines", "2.1 Pflichtfächer"
      - GROSSBUCHSTABEN-Zeilen: "STUDIENPLAN WIRTSCHAFTSINFORMATIK"

    Gibt None zurück, wenn keine Überschrift erkannt wird.
    """
    if not text:
        return None

    # Nur die ersten 8 Zeilen prüfen (Überschriften stehen meist am Seitenanfang)
    for line in text.strip().splitlines()[:8]:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Nummeriertes Heading: "§ 1", "2.", "2.1."
        if re.match(r'^(§\s*\d+|\d+\.(\d+\.)*)\s+\S', line):
            return line

        # Vollständige Großbuchstaben-Zeile (keine reine Zahl)
        if line == line.upper() and len(line) > 3 and not line.isdigit():
            return line

    return None


# ── Datenbankoperationen ─────────────────────────────────────────────────────

def get_or_create_study_program(code: str, name: str) -> str:
    """
    Gibt die UUID eines Studiengangs zurück.
    Existiert der Studiengang noch nicht, wird er angelegt.

    :param code: Studienkennzahl, z.B. "033 526"
    :param name: Vollständiger Name, z.B. "Wirtschaftsinformatik BSc"
    """
    result = supabase.table("study_programs").select("id").eq("code", code).execute()
    if result.data:
        return result.data[0]["id"]

    # Studiengang existiert noch nicht → neu anlegen
    insert = supabase.table("study_programs").insert({"code": code, "name": name}).execute()
    return insert.data[0]["id"]


def document_exists(filename: str, study_program_id: str) -> bool:
    """
    Duplikat-Check: Wurde dieses PDF für diesen Studiengang bereits hochgeladen?
    Verhindert doppelte Chunks in der Datenbank.
    """
    result = (
        supabase.table("documents")
        .select("id")
        .eq("filename", filename)
        .eq("study_program_id", study_program_id)
        .execute()
    )
    return len(result.data) > 0


# ── Haupt-Pipeline ───────────────────────────────────────────────────────────

def process_pdf(pdf_bytes: bytes, filename: str, study_program_id: str, user_id: str) -> int:
    """
    Verarbeitet ein PDF vollständig und speichert alle Daten in Supabase.

    Schritte:
      1. Duplikat-Check
      2. PDF in Supabase Storage hochladen
      3. Dokument-Eintrag in 'documents'-Tabelle anlegen
      4. Seitenweise Text + Tabellen extrahieren
      5. Chunks mit Metadaten erzeugen
      6. Embeddings generieren (E5-Modell)
      7. Chunks in 'chunks'-Tabelle speichern
      8. Dokument-Status auf 'processed' setzen

    :param pdf_bytes: Rohe PDF-Bytes (z.B. von st.file_uploader)
    :param filename:  Originaldateiname, z.B. "curriculum_wi.pdf"
    :param study_program_id: UUID des zugehörigen Studiengangs
    :param user_id:   UUID des hochladenden Users (für RLS-Policy)
    :returns: Anzahl der erstellten Chunks
    """
    import pdfplumber

    # ── Schritt 1: Duplikat-Check ────────────────────────────────────────────
    if document_exists(filename, study_program_id):
        raise ValueError(f"'{filename}' wurde für diesen Studiengang bereits hochgeladen.")

    # Studienkennzahl für den Storage-Pfad holen (Schrägstriche ersetzen)
    program = supabase.table("study_programs").select("code").eq("id", study_program_id).execute()
    program_code = program.data[0]["code"].replace("/", "-") if program.data else "allgemein"
    bucket_path = f"{program_code}/{filename}"   # z.B. "033-526/curriculum_wi.pdf"

    # ── Schritt 2: PDF in Supabase Storage hochladen ─────────────────────────
    supabase.storage.from_(BUCKET).upload(
        bucket_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    # ── Schritt 3: Dokument-Eintrag anlegen (Status = "processing") ──────────
    doc_result = supabase.table("documents").insert({
        "user_id":          user_id,
        "filename":         filename,
        "bucket_path":      bucket_path,
        "study_program_id": study_program_id,
        "status":           "processing",   # wird am Ende auf "processed" gesetzt
    }).execute()
    document_id = doc_result.data[0]["id"]  # UUID des neuen Dokument-Eintrags

    try:
        # ── Schritt 4: Seitenweise Text- und Tabellen-Extraktion ─────────────
        chunks_with_meta = []  # Liste von {"content", "page_number", "section_heading"}

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):

                # Rohtext der Seite extrahieren (None → leerer String)
                page_text = page.extract_text() or ""

                # Inhaltsverzeichnis-Seiten überspringen:
                # viele ". ." Sequenzen = Leitpunkte im ToC
                if page_text.count(". .") > 8:
                    continue

                # Tabellen extrahieren und als Markdown-Strings aufbereiten
                tables = page.extract_tables() or []
                table_blocks = [table_to_markdown(t) for t in tables if t]

                # Text und Tabellen zu einem kombinierten Seiteninhalt zusammenführen
                combined = page_text
                if table_blocks:
                    combined += "\n\n" + "\n\n".join(table_blocks)

                if not combined.strip():
                    continue   # leere Seite überspringen

                # Überschrift der Seite erkennen (für Metadaten)
                heading = extract_section_heading(page_text)

                # ── Schritt 5: Chunks für diese Seite erzeugen ───────────────
                for chunk in chunk_text(combined):
                    chunks_with_meta.append({
                        "content":         chunk,
                        "page_number":     page_num,
                        "section_heading": heading,   # None wenn nicht erkannt
                    })

        # ── Schritt 6: Embeddings für alle Chunks auf einmal generieren ───────
        # Alle Texte werden als Batch verarbeitet (effizienter als einzeln)
        embed_service = EmbeddingService()
        embeddings = embed_service.embed_texts([c["content"] for c in chunks_with_meta])

        # ── Schritt 7: Chunks + Metadaten in Supabase speichern ──────────────
        for i, (chunk_meta, vector) in enumerate(zip(chunks_with_meta, embeddings)):
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk_meta["content"],
                "embedding":   vector,          # 768-dim Vektor (E5-Modell)
                "chunk_index": i,
                "metadata": {
                    # Angereichertes Metadaten-Objekt für spätere Filterung & Anzeige
                    "source_filename":  filename,
                    "page_number":      chunk_meta["page_number"],
                    "section_heading":  chunk_meta["section_heading"],
                    "chunk_index":      i,
                },
            }).execute()

        # ── Schritt 8: Dokument als erfolgreich verarbeitet markieren ─────────
        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        # Bei Fehler: Dokument als fehlgeschlagen markieren, dann Exception weiterwerfen
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks_with_meta)


def process_ics(ics_bytes: bytes, filename: str, user_id: str) -> int:
    """
    Verarbeitet eine ICS-Kalender-Datei und speichert die Events in Supabase.

    Die ICS-Datei wird temporär auf der Festplatte gespeichert, da ingest_ics
    einen Dateipfad erwartet (kein Bytes-Objekt).

    :returns: Anzahl der gespeicherten Events des Users
    """
    import tempfile
    from ingest_ics import ingest_ics

    # ICS-Bytes in temporäre Datei schreiben (ingest_ics braucht einen Pfad)
    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        tmp.write(ics_bytes)
        tmp_path = tmp.name

    try:
        ingest_ics(tmp_path, user_id)
    finally:
        # Temporäre Datei immer löschen, auch bei Fehlern
        os.unlink(tmp_path)

    # Anzahl der gespeicherten Events zurückgeben
    result = supabase.table("events").select("id", count="exact").eq("user_id", user_id).execute()
    return result.count or 0
