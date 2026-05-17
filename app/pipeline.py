"""
pipeline.py – Zentrale ETL-Pipeline des JKU Study Assistants.
==============================================================

  PDF-Bytes  →  Supabase Storage (Backup der Originaldatei)
             →  Seitenweise Text- & Tabellen-Extraktion (pdfplumber)
             →  Chunking (chunking.py)
             →  Embeddings (embeddings.py / E5-Modell)
             →  Chunks + Metadaten in Supabase speichern

ICS-Bytes         →  Kalender-Events parsen  →  Supabase (events)
Studienerfolg PDF/CSV  →  Noten & ECTS parsen  →  Supabase (completed_courses)

Abhaengigkeiten:
  pip install pdfplumber supabase python-dotenv
"""

import io
import re
import os
from typing import Optional
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

TABLE_SETTINGS_LINES = {
    "vertical_strategy":   "lines_strict",
    "horizontal_strategy": "lines_strict",
    "snap_tolerance":      5,
    "join_tolerance":      3,
    "edge_min_length":     10,
}

TABLE_SETTINGS_TEXT = {
    "vertical_strategy":   "text",
    "horizontal_strategy": "text",
    "snap_tolerance":      8,
    "join_tolerance":      5,
    "edge_min_length":     10,
}


# ===============================================================================
# HILFSFUNKTIONEN - PDF-Parsing
# ===============================================================================

def table_to_markdown(table: list) -> str:
    """
    Wandelt eine pdfplumber-Tabelle in einen Markdown-Tabellenstring um.
    Forward-Fill fuer zusammengefuehrte Zellen (Merged Cells).
    """
    if not table or not table[0]:
        return ""

    num_cols    = max(len(row) for row in table)
    last_values = [""] * num_cols
    filled_table = []

    for row in table:
        new_row = []
        for col_idx in range(num_cols):
            raw_cell = row[col_idx] if col_idx < len(row) else None
            val = str(raw_cell or "").replace("\n", " ").strip()
            if val:
                last_values[col_idx] = val
            else:
                val = last_values[col_idx]
            new_row.append(val)
        filled_table.append(new_row)

    rows = ["| " + " | ".join(row) + " |" for row in filled_table]
    if not rows:
        return ""

    separator = "| " + " | ".join(["---"] * num_cols) + " |"
    rows.insert(1, separator)
    return "\n".join(rows)


def detect_two_column_layout(page) -> bool:
    """
    Erkennt ob eine PDF-Seite ein zweispaltiges Layout hat.
    Prueft ob mindestens 30% der Woerter links und 30% rechts der Seitenmitte stehen.
    """
    words = page.extract_words()
    if not words or len(words) < 10:
        return False

    page_mid = page.width / 2
    margin   = page.width * 0.10

    left_words  = [w for w in words if w["x1"] < page_mid - margin]
    right_words = [w for w in words if w["x0"] > page_mid + margin]

    total = len(words)
    left_ratio  = len(left_words)  / total
    right_ratio = len(right_words) / total
    return left_ratio >= 0.30 and right_ratio >= 0.30


def _extract_column_content(col_page) -> str:
    """Extrahiert Text und Tabellen aus einem zugeschnittenen Spalten-Bereich."""
    return _extract_regions(col_page)


def _extract_regions(page) -> str:
    """
    Kernlogik der Seitenextraktion: Text und Tabellen in Leserichtung kombinieren.
    Versucht zuerst Linien-Erkennung, faellt auf Text-basierte Erkennung zurueck.
    """
    table_objects = page.find_tables(table_settings=TABLE_SETTINGS_LINES)
    if not table_objects:
        table_objects = page.find_tables(table_settings=TABLE_SETTINGS_TEXT)

    if not table_objects:
        return page.extract_text() or ""

    sorted_tables = sorted(table_objects, key=lambda t: t.bbox[1])
    regions = []
    prev_bottom = 0

    for table_obj in sorted_tables:
        x0, top, x1, bottom = table_obj.bbox
        top    = max(top, prev_bottom)
        bottom = min(bottom, page.height)

        if top > prev_bottom:
            text_region = page.crop((0, prev_bottom, page.width, top))
            text = text_region.extract_text()
            if text and text.strip():
                regions.append(("text", text))

        table_data = table_obj.extract()
        if table_data:
            regions.append(("table", table_data))

        prev_bottom = bottom

    if prev_bottom < page.height:
        text_region = page.crop((0, prev_bottom, page.width, page.height))
        text = text_region.extract_text()
        if text and text.strip():
            regions.append(("text", text))

    parts = []
    for kind, content in regions:
        if kind == "text":
            parts.append(content)
        else:
            md = table_to_markdown(content)
            if md:
                parts.append(md)

    return "\n\n".join(filter(None, parts))


def extract_page_content(page) -> str:
    """
    Extrahiert den vollstaendigen Inhalt einer PDF-Seite in korrekter Leserichtung.
    Erkennt automatisch zweispaltige Layouts.
    """
    if detect_two_column_layout(page):
        try:
            page_mid  = page.width / 2
            left_col  = page.crop((0,        0, page_mid,   page.height))
            right_col = page.crop((page_mid, 0, page.width, page.height))
            return "\n\n".join(filter(None, [
                _extract_regions(left_col),
                _extract_regions(right_col),
            ]))
        except Exception:
            # Bounding-Box-Fehler bei manchen PDFs -> Fallback auf einspaltige Extraktion
            pass

    return _extract_regions(page)


def extract_section_heading(text: str) -> Optional[str]:
    """
    Erkennt die erste Abschnittsueberschrift aus dem Rohtext einer Seite.
    """
    if not text:
        return None

    for line in text.strip().splitlines()[:8]:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if re.match(r'^(§\s*\d+[a-z]?|\d+\.(\d+\.)*)\s+\S', line):
            return line
        if line == line.upper() and len(line) > 3 and not line.isdigit():
            return line

    return None


# ===============================================================================
# DATENBANKOPERATIONEN
# ===============================================================================

def erkennen_abschlussart(pdf_bytes: bytes) -> Optional[str]:
    """
    Erkennt automatisch die Abschlussart eines Studiums aus dem PDF-Inhalt.
    Durchsucht die ersten 5 Seiten nach Schluesselwoertern.
    """
    import pdfplumber

    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:5]:
            text += (page.extract_text() or "") + "\n"

    text_lower = text.lower()
    kandidaten = {
        "Master":   len(re.findall(r'\bmaster\b|masterstudium|master of science|master of arts|m\.sc\b|msc\b', text_lower)),
        "Bachelor": len(re.findall(r'\bbachelor\b|bachelorstudium|bachelor of science|bachelor of arts|b\.sc\b|bsc\b', text_lower)),
        "Diplom":   len(re.findall(r'\bdiplom\b|diplomstudium|dipl\.-ing\b|magisterstudium|\bmag\.\b', text_lower)),
        "Lehramt":  len(re.findall(r'\blehramt\b', text_lower)),
        "Doktorat": len(re.findall(r'\bdoktorat\b|\bphd\b', text_lower)),
    }
    bester = max(kandidaten, key=kandidaten.get)
    return bester if kandidaten[bester] > 0 else None


def get_or_create_study_program(code: str, name: str, degree_type: Optional[str] = None) -> str:
    """
    Gibt die UUID eines Studiengangs zurueck. Legt ihn an, falls er noch nicht existiert.
    """
    result = supabase.table("study_programs").select("id").eq("code", code).execute()
    if result.data:
        return result.data[0]["id"]

    row = {"code": code, "name": name}
    if degree_type:
        row["degree_type"] = degree_type

    insert = supabase.table("study_programs").insert(row).execute()
    return insert.data[0]["id"]


def document_exists(filename: str, study_program_id: str) -> bool:
    """Prueft ob ein PDF fuer diesen Studiengang bereits in der Datenbank ist."""
    result = (
        supabase.table("documents")
        .select("id")
        .eq("filename", filename)
        .eq("study_program_id", study_program_id)
        .execute()
    )
    return len(result.data) > 0


# ===============================================================================
# HAUPT-PIPELINE: PDF (nur Admin)
# ===============================================================================

def process_pdf(pdf_bytes: bytes, filename: str, study_program_id: str, user_id: str) -> int:
    """
    Verarbeitet ein Curriculum-PDF vollstaendig und speichert alle Daten in Supabase.
    NUR fuer Admin-Nutzung.

    :returns: Anzahl der erstellten Chunks
    """
    import pdfplumber

    if document_exists(filename, study_program_id):
        raise ValueError(f"'{filename}' wurde fuer diesen Studiengang bereits hochgeladen.")

    program = supabase.table("study_programs").select("code").eq("id", study_program_id).execute()
    program_code = program.data[0]["code"].replace("/", "-") if program.data else "allgemein"
    bucket_path  = f"{program_code}/{filename}"

    supabase.storage.from_(BUCKET).upload(
        bucket_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    doc_result = supabase.table("documents").insert({
        "user_id":          user_id,
        "filename":         filename,
        "bucket_path":      bucket_path,
        "study_program_id": study_program_id,
        "status":           "processing",
    }).execute()
    document_id = doc_result.data[0]["id"]

    try:
        chunks_with_meta = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text_raw = page.extract_text() or ""

                if page_text_raw.count(". .") > 8:
                    continue

                combined = extract_page_content(page)
                if not combined.strip():
                    continue

                heading        = extract_section_heading(page_text_raw)
                page_has_table = "|" in combined

                for chunk in chunk_text(combined):
                    chunk_has_table = "|" in chunk
                    chunk_type = (
                        "table" if chunk.strip().startswith("|")
                        else "mixed" if chunk_has_table
                        else "text"
                    )
                    chunks_with_meta.append({
                        "content":         chunk,
                        "page_number":     page_num,
                        "section_heading": heading,
                        "has_table":       chunk_has_table,
                        "chunk_type":      chunk_type,
                    })

        embed_service = EmbeddingService()
        embeddings    = embed_service.embed_texts([c["content"] for c in chunks_with_meta])

        for i, (chunk_meta, vector) in enumerate(zip(chunks_with_meta, embeddings)):
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk_meta["content"],
                "embedding":   vector,
                "chunk_index": i,
                "metadata": {
                    "source_filename":  filename,
                    "page_number":      chunk_meta["page_number"],
                    "section_heading":  chunk_meta["section_heading"],
                    "chunk_index":      i,
                    "has_table":        chunk_meta["has_table"],
                    "chunk_type":       chunk_meta["chunk_type"],
                },
            }).execute()

        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks_with_meta)


# ===============================================================================
# USER-PIPELINE: ICS-Kalender
# ===============================================================================

def process_ics(ics_bytes: bytes, filename: str, user_id: str) -> int:
    """
    Verarbeitet eine KUSSS-ICS-Datei und speichert Events in der events-Tabelle.

    :returns: Anzahl importierter Events
    """
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


# ===============================================================================
# USER-PIPELINE: Studienerfolg (Noten-Nachweis)
# ===============================================================================

_NOTE_LABELS = {
    1: "Sehr Gut", 2: "Gut", 3: "Befriedigend", 4: "Genuegend", 5: "Nicht Genuegend",
}


def _parse_grade_rows_from_text(text: str) -> list[dict]:
    """
    Extrahiert Noten-Eintraege aus dem Rohtext eines KUSSS-Studienerfolgs (PDF).
    """
    row_pattern = re.compile(
        r'(?m)^(\d{3}\.\d{3})\s+'
        r'(.+?)\s+'
        r'(\d+[.,]\d+|\d+)\s+'
        r'(\w+)\s+'
        r'([1-5])\s+'
        r'(\d{2}\.\d{2}\.\d{4})'
    )
    rows = []
    for m in row_pattern.finditer(text):
        ects_raw = m.group(3).replace(",", ".")
        grade    = int(m.group(5))
        rows.append({
            "course_code":  m.group(1),
            "course_name":  m.group(2).strip(),
            "ects":         float(ects_raw),
            "course_type":  m.group(4),
            "grade":        grade,
            "grade_label":  _NOTE_LABELS.get(grade),
            "passed":       grade <= 4,
            "exam_date":    m.group(6),
        })
    return rows


def _parse_grade_rows_from_csv(text: str) -> list[dict]:
    """
    Extrahiert Noten-Eintraege aus einem KUSSS-CSV-Export (Semikolon-getrennt).
    """
    import csv

    rows   = []
    lines  = text.strip().splitlines()
    reader = csv.DictReader(lines, delimiter=";")

    def _norm(key: str) -> str:
        return key.strip().lstrip("\ufeff").lower()

    for raw_row in reader:
        row = {_norm(k): v.strip() for k, v in raw_row.items() if k}
        try:
            ects_raw = row.get("ects", "0").replace(",", ".")
            grade    = int(row.get("note", row.get("grade", "5")))
            rows.append({
                "course_code":  row.get("lv-nummer", row.get("course_code", "")),
                "course_name":  row.get("lv-name",   row.get("course_name", "")),
                "ects":         float(ects_raw),
                "course_type":  row.get("typ",        row.get("type", "")),
                "grade":        grade,
                "grade_label":  _NOTE_LABELS.get(grade),
                "passed":       grade <= 4,
                "exam_date":    row.get("datum",      row.get("date", "")),
            })
        except (ValueError, KeyError):
            continue

    return rows


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrahiert den gesamten Rohtext aus einem PDF (alle Seiten zusammengefuehrt)."""
    import pdfplumber
    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text


def _upsert_grades(grades: list[dict], user_id: str) -> int:
    """
    Speichert Noten-Eintraege in completed_courses (Upsert per user_id + lva_nr).
    """
    success = 0
    for grade in grades:
        try:
            row = {
                "user_id":     user_id,
                "lva_nr":      grade["course_code"],
                "course_name": grade["course_name"],
                "course_type": grade["course_type"],
                "ects":        grade["ects"],
                "grade":       grade["grade"],
                "grade_label": grade["grade_label"],
                "passed":      grade["passed"],
                "exam_date":   grade["exam_date"],
            }
            supabase.table("completed_courses").upsert(
                row, on_conflict="user_id,lva_nr"
            ).execute()
            success += 1
        except Exception as e:
            print(f"  Fehler bei {grade.get('course_code')}: {e}")
    return success


def process_studienerfolg(file_bytes: bytes, filename: str, user_id: str) -> dict:
    """
    Verarbeitet den KUSSS-Studienerfolg (Notennachweis) eines Studenten.

    Unterstuetzte Formate: PDF, CSV
    Speichert Noten in completed_courses (RLS-geschuetzt, nur eigene Daten sichtbar).

    :returns: Dict mit total/passed/failed/ects_total fuer das Frontend
    """
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        raw_text = _extract_text_from_pdf(file_bytes)
        grades   = _parse_grade_rows_from_text(raw_text)
    elif ext == "csv":
        raw_text = file_bytes.decode("utf-8-sig", errors="replace")
        grades   = _parse_grade_rows_from_csv(raw_text)
    else:
        raise ValueError(f"Unbekanntes Dateiformat: '{ext}'. Bitte PDF oder CSV hochladen.")

    if not grades:
        raise ValueError(
            "Keine Noten-Eintraege gefunden. "
            "Stelle sicher, dass du den offiziellen KUSSS-Studienerfolg hochlaedst."
        )

    saved         = _upsert_grades(grades, user_id)
    passed_grades = [g for g in grades if g["passed"]]
    failed_grades = [g for g in grades if not g["passed"]]
    ects_total    = sum(g["ects"] for g in passed_grades)

    return {
        "total":      len(grades),
        "saved":      saved,
        "passed":     len(passed_grades),
        "failed":     len(failed_grades),
        "ects_total": round(ects_total, 1),
    }