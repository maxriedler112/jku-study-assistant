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
from pdf_chunking import chunk_curriculum_pdf

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
    Konvertiert eine pdfplumber-Tabelle in ein Markdown-Format.
    Nutzt Forward-Fill, um leere Zellen nach Merged Cells mit dem letzten Wert zu füllen.
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
    Prüft anhand der Wortverteilung (mind. 30% links und rechts der Mitte mit Margin),
    ob die PDF-Seite ein zweispaltiges Layout besitzt.
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
    """
    Extrahiert Text und Tabellen aus einem vordefinierten, zugeschnittenen Spaltenbereich.
    """
    return _extract_regions(col_page)


def _extract_regions(page) -> str:
    """
    Extrahiert Text und Tabellen einer Seite chronologisch in Leserichtung von oben nach unten.
    Vermeidet Textdopplungen durch horizontales Zuschneiden (Cropping) zwischen den Tabellen.
    """
    # 1. Versuche Tabellen über Linien zu finden, Fallback auf textbasierte Erkennung
    table_objects = page.find_tables(table_settings=TABLE_SETTINGS_LINES)
    if not table_objects:
        table_objects = page.find_tables(table_settings=TABLE_SETTINGS_TEXT)

    if not table_objects:
        return page.extract_text() or ""

    # Tabellen von oben nach unten sortieren
    sorted_tables = sorted(table_objects, key=lambda t: t.bbox[1])
    regions = []
    prev_bottom = 0

    # 2. Iteriere durch Tabellen und extrahiere den Text jeweils DAZWISCHEN
    for table_obj in sorted_tables:
        x0, top, x1, bottom = table_obj.bbox
        top    = max(top, prev_bottom)
        bottom = min(bottom, page.height)

        # Reiner Textbereich über der aktuellen Tabelle extrahieren
        if top > prev_bottom:
            text_region = page.crop((0, prev_bottom, page.width, top))
            text = text_region.extract_text()
            if text and text.strip():
                regions.append(("text", text))

        # Tabellendaten sichern
        table_data = table_obj.extract()
        if table_data:
            regions.append(("table", table_data))

        prev_bottom = bottom

    # 3. Letzten Textabschnitt unter der letzten Tabelle extrahieren
    if prev_bottom < page.height:
        text_region = page.crop((0, prev_bottom, page.width, page.height))
        text = text_region.extract_text()
        if text and text.strip():
            regions.append(("text", text))

    # 4. Regionen zusammenführen und Tabellen in Markdown übersetzen
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
    Steuert die Seitenextraktion: Splittet zweispaltige Layouts in zwei Spalten-Objekte
    oder verarbeitet die Seite direkt einspaltig.
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
            # Fallback bei Bounding-Box-Fehlern (z.B. beschädigte PDFs)
            pass

    return _extract_regions(page)


def extract_section_heading(text: str) -> Optional[str]:
    """
    Scannt die ersten Zeilen einer Seite nach Mustern für Überschriften (z.B. '§ 1', '1.1' oder UPPERCASE).
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
    Identifiziert die Abschlussart (Bachelor, Master etc.) per Regex-Häufigkeitszählung
    auf den ersten 5 Seiten des PDFs.
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
    Gibt die UUID eines Studiengangs aus Supabase zurück oder legt ihn neu an, falls nicht vorhanden.
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
    """
    Prüft via Duplikatcheck in Supabase, ob die Datei für den Studiengang bereits existiert.
    """
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
    Admin-Funktion: Lädt das PDF in den Storage, extrahiert den Inhalt seitenweise,
    unterteilt ihn generisch in Chunks, generiert Vektor-Embeddings und speichert alles in Supabase.
    """
    import pdfplumber

    if document_exists(filename, study_program_id):
        raise ValueError(f"'{filename}' wurde fuer diesen Studiengang bereits hochgeladen.")

    # 1. Datei-Upload in Supabase Storage S3-Bucket
    program = supabase.table("study_programs").select("code").eq("id", study_program_id).execute()
    program_code = program.data[0]["code"].replace("/", "-") if program.data else "allgemein"
    bucket_path  = f"{program_code}/{filename}"

    supabase.storage.from_(BUCKET).upload(
        bucket_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    # 2. Dokument-Eintrag ("processing") erstellen
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

        # 3. Seitenweise Text extrahieren & filtern (z.B. Inhaltsverzeichnisse ausschließen)
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text_raw = page.extract_text() or ""

                if page_text_raw.count(". .") > 8: # Überspringe typische JKU-Inhaltsverzeichnisse
                    continue

                combined = extract_page_content(page)
                if not combined.strip():
                    continue

                heading        = extract_section_heading(page_text_raw)
                page_has_table = "|" in combined

                # 4. Text in kleinere Chunks spalten und Typen klassifizieren
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

        # 5. Massen-Embeddings über den EmbeddingService anfordern
        embed_service = EmbeddingService()
        embeddings    = embed_service.embed_texts([c["content"] for c in chunks_with_meta])

        # 6. Chunks inkl. Vektoren in Supabase inserten
        for i, (chunk_meta, vector) in enumerate(zip(chunks_with_meta, embeddings)):
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk_meta["content"],
                "embedding":   vector,
                "chunk_index": i,
                "metadata": {
                    "source_type":      "curriculum_pdf",
                    "source_filename":  filename,
                    "page_number":      chunk_meta["page_number"],
                    "section_heading":  chunk_meta["section_heading"],
                    "chunk_index":      i,
                    "has_table":        chunk_meta["has_table"],
                    "chunk_type":       chunk_meta["chunk_type"],
                },
            }).execute()

        # Status erfolgreich updaten
        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks_with_meta)


# ===============================================================================
# ADMIN-PIPELINE: Curriculum-PDF mit strukturierten Metadaten
# ===============================================================================

def process_pdf_curriculum(
    pdf_bytes:  bytes,
    filename:   str,
    program_id: str,
    user_id:    str,
    degree:     str,
    study_program: str,
) -> int:
    """
    Spezialisierte Admin-Funktion: Verarbeitet Curriculum-PDFs mittels intelligenterem,
    strukturiertem JKU-Curriculum-Chunking (`pdf_chunking.py`). Verknüpft direkt Studienrichtung & Grad.
    """
    from pdf_chunking import chunk_curriculum_pdf

    # 1. Duplikat-Check
    existing = (
        supabase.table("documents")
        .select("id")
        .eq("filename", filename)
        .eq("study_program_id", program_id)
        .execute()
    )
    if existing.data:
        raise ValueError(f"PDF '{filename}' wurde bereits verarbeitet.")

    # 2. Dokumentenstatus initialisieren
    doc_result = supabase.table("documents").insert({
        "filename":         filename,
        "user_id":      user_id,
        "study_program_id": program_id,
        "status":           "processing",
    }).execute()
    document_id = doc_result.data[0]["id"]

    try:
        # 3. Strukturiertes Chunking speziell für Curricula ausführen
        chunks = chunk_curriculum_pdf(pdf_bytes, degree=degree, study_program=study_program)

        if not chunks:
            raise ValueError("Keine Chunks erzeugt – PDF leer oder nicht lesbar.")

        # 4. Embeddings generieren
        embed_service = EmbeddingService()
        texts = [c["content"] for c in chunks]
        embeddings = embed_service.embed_texts(texts)

        # 5. Speichern mit erweiterten, strukturierten Metadaten für das Web-UI
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            meta = {
                **chunk["metadata"],
                "source_filename": filename,
                "chunk_index":     i,
                "study_program":   study_program,
                "degree":          degree,
            }
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk["content"],
                "embedding":   vector,
                "chunk_index": i,
                "metadata":    meta,
            }).execute()

        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks)


# ===============================================================================
# USER-PIPELINE: ICS-Kalender
# ===============================================================================

def process_ics(ics_bytes: bytes, filename: str, user_id: str) -> int:
    """
    User-Funktion: Schreibt JKU KUSSS-Kalendertermine über eine temporäre Datei
    mittels der `ingest_ics`-Logik in die Supabase 'events'-Tabelle.
    """
    import tempfile
    from ingest_ics import ingest_ics

    # Temporäre Datei erzeugen, um dem Parser einen lokalen Dateipfad zu übergeben
    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        tmp.write(ics_bytes)
        tmp_path = tmp.name

    try:
        ingest_ics(tmp_path, user_id)
    finally:
        os.unlink(tmp_path) # Tempfile nach Verarbeitung sauber löschen

    result = supabase.table("events").select("id", count="exact").eq("user_id", user_id).execute()
    return result.count or 0


def _parse_grade_rows_from_csv(text: str) -> list[dict]:
    """
    User-Hilfsfunktion: Parst einen KUSSS-Notenexport im CSV-Format (Semikolon-separiert)
    und bereitet die Spalten vereinheitlicht für das Datenbank-Schema vor.
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
    """
    User-Hilfsfunktion: Extrahiert den rohen, unstrukturierten Text aller PDF-Seiten
    ohne Tabellenerkennung als einfachen String.
    """
    import pdfplumber
    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text


def _upsert_grades(grades: list[dict], user_id: str) -> int:
    """
    User-Hilfsfunktion: Führt ein Upsert für Noten in 'completed_courses' durch.
    Verhindert Duplikate bei mehrfachem Upload durch Unique-Constraint (user_id + lva_nr).
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


def _parse_grade_rows_from_text(text: str) -> list[dict]:
    """
    FALLBACK: Altes Regex-basiertes Textparsing für Noten.
    Dient nur noch als Sicherheitsnetz, falls die Tabellenextraktion versagt.
    """
    return []


def _parse_studienerfolg_pdf_tables(pdf_bytes: bytes) -> list[dict]:
    """
    User-Hilfsfunktion: Parst das KUSSS-Erfolgsnachweis-PDF gezielt über Tabellenstrukturen.
    Extrahiert Kursname, LVA-Nummer, Typ, ECTS, Datum und Note aus der 6-Spalten-Matrix.
    """
    import pdfplumber

    GRADE_MAP = {
        "sehr gut": 1,
        "gut": 2,
        "befriedigend": 3,
        "genügend": 4,
        "nicht genügend": 5,
    }
    LVA_TYPES = {"VK", "VL", "UE", "KS", "KV", "SE", "PR", "PJ", "KT", "PS"}

    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.find_tables(table_settings=TABLE_SETTINGS_LINES)
            for table_obj in tables:
                table_data = table_obj.extract()
                # Validierung: Nur echte KUSSS-Notentabellen haben exakt 6 Spalten
                if not table_data or len(table_data[0]) != 6:
                    continue

                for raw_row in table_data:
                    if not raw_row or len(raw_row) < 6:
                        continue

                    # Zeilen ohne gültigen LVA-Typ (z.B. Tabellen-Header) überspringen
                    typ = str(raw_row[1] or "").strip()
                    if typ not in LVA_TYPES:
                        continue

                    # ── Kursname + LVA-Nr aus Spalte 0 isolieren ─────────────────
                    cell0 = str(raw_row[0] or "")
                    lines = cell0.split("\n")
                    course_name = lines[0].strip()

                    lva_nr = ""
                    course_code = ""
                    if len(lines) > 1:
                        second_line = lines[1].strip()
                        # Extrahiere numerische LVA-Nr (z.B. 259.016)
                        nr_match = re.search(r'(\d{3}\.\S+)', second_line)
                        if nr_match:
                            lva_nr = nr_match.group(1)
                        # Alphanumerischen Äquivalenz-Code sichern
                        code_match = re.match(r'(\S+)', second_line)
                        if code_match:
                            course_code = code_match.group(1)

                    effective_lva_nr = lva_nr or course_code

                    # ── ECTS, Datum und Note parsen & mappen ─────────────────────
                    try:
                        ects = float(str(raw_row[3] or "0").replace(",", "."))
                    except ValueError:
                        continue

                    datum = str(raw_row[4] or "").replace("\n", "").strip()

                    note_raw = str(raw_row[5] or "").replace("\n", " ").strip()
                    note_lower = note_raw.lower()
                    grade = GRADE_MAP.get(note_lower)
                    
                    # Kurs ist bestanden bei "mit erfolg teilgenommen" ODER Note 1-4
                    passed = note_lower == "mit erfolg teilgenommen" or (grade is not None and grade <= 4)

                    rows.append({
                        "course_code":  effective_lva_nr,
                        "course_name":  course_name,
                        "ects":         ects,
                        "course_type":  typ,
                        "grade":        grade,
                        "grade_label":  note_raw,
                        "passed":       passed,
                        "exam_date":    datum,
                    })

    return rows


def process_studienerfolg(file_bytes: bytes, filename: str, user_id: str) -> dict:
    """
    User-Hauptfunktion: Steuert den Studienerfolgs-Import für Studierende. Splittet nach Dateiendung (PDF/CSV),
    startet das jeweilige Parsing, triggert den Datenbank-Upsert und berechnet ein Statistik-Summary.
    """
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        # Versuche primär die saubere Tabellenextraktion
        grades = _parse_studienerfolg_pdf_tables(file_bytes)
        if not grades:
            # Fallback bei stark formatierten/unbekannten PDF-Dateien
            raw_text = _extract_text_from_pdf(file_bytes)
            grades = _parse_grade_rows_from_text(raw_text)
    elif ext == "csv":
        raw_text = file_bytes.decode("utf-8-sig", errors="replace")
        grades = _parse_grade_rows_from_csv(raw_text)
    else:
        raise ValueError(f"Unbekanntes Dateiformat: '{ext}'. Bitte PDF oder CSV hochladen.")

    if not grades:
        raise ValueError(
            "Keine Noten-Einträge gefunden. "
            "Stelle sicher, dass du den offiziellen KUSSS-Studienerfolg hochlädst."
        )

    # In Datenbank sichern
    saved = _upsert_grades(grades, user_id)
    
    # Statistiken für den API-Response berechnen
    passed_grades = [g for g in grades if g["passed"]]
    failed_grades = [g for g in grades if not g["passed"]]
    ects_total = sum(g["ects"] for g in passed_grades)

    return {
        "total":      len(grades),
        "saved":      saved,
        "passed":     len(passed_grades),
        "failed":     len(failed_grades),
        "ects_total": round(ects_total, 1),
    }