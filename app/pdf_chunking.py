"""
pdf_chunking.py – Spezialisiertes Chunking für JKU Curriculum-PDFs.
====================================================================

Erzeugt Chunks mit Web-Chunk-kompatiblen Metadaten, damit das Retrieval-
Modell PDF- und Web-Chunks gleich gut durchsuchen und kombinieren kann.

STRATEGIE:
  1. Echte Tabellen (lines_strict) → pro Zeile ein strukturierter Chunk
     mit Metadaten: course_name, ects, code, module_name, section, degree
  2. Fließtext (§-Absätze) → Contextual Chunks mit section_heading als
     Kontext-Header (identisch zur bestehenden chunking.py-Logik)
  3. Keine Text-basierte Tabellenerkennung mehr → vermeidet Fließtext-
     Fehlklassifikation, die bisher riesige (~5000 Zeichen) Pseudo-Tabellen erzeugte

WARUM EIGENE DATEI?
  Die bestehende chunking.py + pipeline.py bleiben vollständig unverändert.
  Nur admin_ingest_pdf.py (und process_pdf in pipeline.py) ruft diese
  Funktionen zusätzlich auf.

METADATEN-KOMPATIBILITÄT (Web-Chunk-Schema):
  {
    "ects":           "6",
    "degree":         "Bachelor",
    "lva_name":       "Datenmodellierung",          # Modul/Fach-Name
    "has_table":      true,
    "chunk_type":     "curriculum_row",              # neu: ein Kurs pro Chunk
    "source_url":     None,                          # nur Web-Chunks
    "chunk_index":    42,
    "course_name":    "Datenmodellierung",
    "course_type":    None,                          # nur Web-Chunks (VL/UE/KV)
    "module_name":    "Grundlagen der Wirtschaftsinformatik",
    "source_type":    "curriculum_pdf",
    "study_program":  "Wirtschaftsinformatik",
    "overview_level": "module",                      # "fach" | "module" | "overview"
    "section":        "§ 7 Pflichtfächer",
    "lva_code":       "526GLWNDAM13",                # Studienfachkennung / Code
  }

Abhängigkeiten: pdfplumber, chunking.py (clean_text, chunk_text)
"""

import re
import io
from typing import Optional

try:
    import pdfplumber
except ImportError:
    raise ImportError("pdfplumber fehlt: pip install pdfplumber --break-system-packages")


# ─────────────────────────────────────────────────────────────────────────────
# KONSTANTEN
# ─────────────────────────────────────────────────────────────────────────────

TABLE_SETTINGS_LINES = {
    "vertical_strategy":   "lines_strict",
    "horizontal_strategy": "lines_strict",
    "snap_tolerance":      5,
    "join_tolerance":      3,
    "edge_min_length":     10,
}

# Seiten die übersprungen werden sollen (Inhaltsverzeichnis-Heuristik)
_TOC_MARKER = ". ."
_TOC_THRESHOLD = 8  # mehr als N ". ."-Vorkommen → Inhaltsverzeichnis


# ─────────────────────────────────────────────────────────────────────────────
# HILFSFUNKTIONEN: Tabellen-Parsing
# ─────────────────────────────────────────────────────────────────────────────

def _expand_multiline_cells(table_data: list) -> list[dict]:
    """
    pdfplumber liefert bei mehrzeiligen Zellen den Inhalt per '\\n' zusammengeklebt
    in einer einzigen Datenzeile. Diese Funktion expandiert das zu separaten Zeilen.

    Beispiel Input (raw aus pdfplumber):
      [['Code', 'Bezeichnung', 'ECTS'],
       ['526A\\n526B', 'Datenmodellierung\\nStatistik', '6\\n3']]

    Beispiel Output:
      [{'Code': '526A', 'Bezeichnung': 'Datenmodellierung', 'ECTS': '6'},
       {'Code': '526B', 'Bezeichnung': 'Statistik',         'ECTS': '3'}]
    """
    if not table_data or len(table_data) < 2:
        return []

    header = [str(h or "").strip() for h in table_data[0]]
    # Nur die erste Datenzeile enthält alle Werte (zusammengeklebt)
    data_row = table_data[1]
    cell_lists = [str(cell or "").split("\n") for cell in data_row]
    max_rows = max(len(c) for c in cell_lists) if cell_lists else 0

    rows = []
    for i in range(max_rows):
        row = {}
        for col_idx, col_name in enumerate(header):
            vals = cell_lists[col_idx] if col_idx < len(cell_lists) else []
            row[col_name] = vals[i].strip() if i < len(vals) else ""
        rows.append(row)

    return rows


def _is_overview_table(table_data: list) -> bool:
    """
    Erkennt Übersichtstabellen ohne Code-Spalte (z.B. die Gesamtübersicht
    auf Seite 7: nur 'Bezeichnung' + 'ECTS', kein 'Code'/'Studienfachkennung').
    Diese werden als einzelner prose-artiger Chunk behandelt, nicht zeilenweise.
    """
    if not table_data or not table_data[0]:
        return False
    header = [str(h or "").strip().lower() for h in table_data[0]]
    has_code = any(h in ("code", "studienfachkennung") for h in header)
    return not has_code


def _is_section_header_row(row: dict) -> bool:
    """
    Erkennt Zwischenüberschriften in ECTS-Tabellen wie 'Basiskompetenz' oder
    'Kernkompetenz', die keine echten Kurszeilen sind (ECTS-Zelle leer oder
    enthält nur die Gesamtsumme '180').
    """
    ects = row.get("ECTS", "").strip()
    bez  = row.get("Bezeichnung", "").strip()
    code = row.get("Code", row.get("Studienfachkennung", "")).strip()

    # Zeilen ohne Code und ohne ECTS sind reine Kategorie-Labels
    if not ects and not code:
        return True
    # Die Gesamtzeile
    if bez.lower() == "gesamt":
        return True
    # Kategorie-Labels (Basiskompetenz, Kernkompetenz)
    if bez in ("Basiskompetenz", "Kernkompetenz"):
        return True

    return False


def _detect_section_context(page_text: str, prev_section: str) -> str:
    """
    Erkennt die aktuelle §-Überschrift aus dem Seitenrohtext.
    Gibt den letzten bekannten Abschnitt zurück falls nichts gefunden.
    """
    for line in page_text.splitlines()[:10]:
        line = line.strip()
        if re.match(r'^§\s*\d+[a-z]?\s+\S', line):
            return line
    return prev_section


def _detect_module_context(text_before_table: str) -> str:
    """
    Findet den zugehörigen Modul-/Fach-Namen aus dem Text DIREKT VOR einer Tabelle.

    In §7 stehen Einleitungssätze wie:
      "(6) Das Fach Information Engineering gliedert sich in folgende Module:"
    Wir suchen nur in den letzten 150 Zeichen direkt vor der Tabelle —
    damit werden Einleitungen vorheriger Tabellen nicht fälschlicherweise
    als Modul-Kontext übernommen.
    """
    # Nur die letzten 150 Zeichen — gerade genug für eine Einleitungszeile
    relevant = text_before_table[-150:] if len(text_before_table) > 150 else text_before_table
    m = re.search(r'Das\s+Fach\s+(.+?)\s+gliedert\s+sich', relevant)
    if m:
        return m.group(1).strip()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# KERN: Chunks aus Tabellen
# ─────────────────────────────────────────────────────────────────────────────

def _overview_table_to_text(
    table_data:    list,
    section:       str,
    degree:        str,
    study_program: str,
) -> str:
    """
    Wandelt eine Übersichtstabelle (nur Bezeichnung+ECTS) in einen lesbaren Text.

    WICHTIG: pdfplumber liest diese Tabelle mit einem Offset-Fehler:
    Kategorie-Labels wie 'Basiskompetenz' und 'Kernkompetenz' haben im PDF
    keine eigene ECTS-Zelle, bekommen aber trotzdem einen Wert aus der
    nächsten Zeile zugewiesen. Dadurch verschiebt sich die gesamte ECTS-Spalte.

    Fix: Wir parsen Bezeichnung und ECTS direkt aus den rohen Zell-Listen
    und überspringen Kategorie-Labels manuell, ohne _expand_multiline_cells().
    """
    if not table_data or len(table_data) < 2:
        return ""

    # Rohe Zell-Listen direkt aus pdfplumber
    bez_list  = str(table_data[1][0] or "").split("\n")
    ects_list = str(table_data[1][1] or "").split("\n") if len(table_data[1]) > 1 else []

    # Kategorie-Labels die keine eigene ECTS-Zeile haben
    CATEGORY_LABELS = {"basiskompetenz", "kernkompetenz"}

    # Bezeichnungen ohne Kategorie-Labels → echte Fächer
    faecher = [b.strip() for b in bez_list if b.strip() and b.strip().lower() not in CATEGORY_LABELS]

    lines = [f"Studium: {study_program}. Typ: {degree}. Abschnitt: {section}."]
    lines.append("ECTS-Übersicht:")

    for i, bez in enumerate(faecher):
        if bez.lower() in ("gesamt", "freie studienleistungen"):
            continue
        ects = ects_list[i].strip() if i < len(ects_list) else ""
        if bez and ects:
            lines.append(f"  {bez}: {ects} ECTS")

    # Gesamtsumme explizit hinzufügen
    lines.append("  Gesamt: 180 ECTS")

    return "\n".join(lines) if len(lines) > 2 else ""


def _chunks_from_table(
    table_data:    list,
    section:       str,
    module_name:   str,
    degree:        str,
    study_program: str,
) -> list[dict]:
    """
    Erzeugt pro Kurszeile einen strukturierten Chunk + Metadaten.

    Jeder Chunk enthält:
      - content: lesbarer Text im Format der Web-Chunks
        "Studium: Wirtschaftsinformatik. Typ: Bachelor. Modul: X. Bezeichnung: Y. ECTS: Z."
      - metadata: dict kompatibel mit dem Web-Chunk-Schema

    Zeilen die keine echten Kurse sind (Kategorie-Labels, Gesamtzeilen)
    werden übersprungen.
    """
    rows = _expand_multiline_cells(table_data)
    chunks = []

    # Laufender Kategorie-Kontext (Basiskompetenz / Kernkompetenz)
    current_category = ""

    for row in rows:
        bez  = row.get("Bezeichnung", "").strip()
        ects = row.get("ECTS", "").strip()
        code = row.get("Code", row.get("Studienfachkennung", "")).strip()

        # Kategorie-Labels tracken für nachfolgende Zeilen
        if bez in ("Basiskompetenz", "Kernkompetenz"):
            current_category = bez
            continue

        if _is_section_header_row(row) or not bez:
            continue

        # module_name: explizit > Kategorie > leer
        effective_module = module_name or current_category or ""

        content_parts = [
            f"Studium: {study_program}.",
            f"Typ: {degree}.",
        ]
        if section:
            content_parts.append(f"Abschnitt: {section}.")
        if effective_module:
            content_parts.append(f"Modul: {effective_module}.")
        if code:
            content_parts.append(f"Code: {code}.")
        content_parts.append(f"Bezeichnung: {bez}.")
        if ects:
            content_parts.append(f"ECTS: {ects}.")

        content = " ".join(content_parts)

        meta = {
            "ects":           ects,
            "degree":         degree,
            "lva_name":       bez,
            "has_table":      True,
            "chunk_type":     "curriculum_row",
            "source_url":     None,
            "course_name":    bez,
            "course_type":    None,
            "module_name":    effective_module,
            "source_type":    "curriculum_pdf",
            "study_program":  study_program,
            "overview_level": "module",
            "section":        section,
            "lva_code":       code,
        }

        chunks.append({"content": content, "metadata": meta})

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# KERN: Chunks aus Fließtext
# ─────────────────────────────────────────────────────────────────────────────

def _chunks_from_prose(
    page_text:     str,
    section:       str,
    degree:        str,
    study_program: str,
) -> list[dict]:
    """
    Erzeugt Fließtext-Chunks aus §-Absätzen.

    Nutzt clean_text() + chunk_text() aus der bestehenden chunking.py
    (unverändert). Jeder Chunk bekommt Basis-Metadaten ohne Kurs-Details.
    """
    from chunking import clean_text, chunk_text

    cleaned = clean_text(page_text)
    if not cleaned.strip():
        return []

    raw_chunks = chunk_text(cleaned)
    result = []

    for raw in raw_chunks:
        # Zu kurze oder bedeutungslose Chunks überspringen
        if len(raw.strip()) < 40:
            continue

        meta = {
            "ects":           None,
            "degree":         degree,
            "lva_name":       None,
            "has_table":      False,
            "chunk_type":     "prose",
            "source_url":     None,
            "course_name":    None,
            "course_type":    None,
            "module_name":    None,
            "source_type":    "curriculum_pdf",
            "study_program":  study_program,
            "overview_level": "overview",
            "section":        section,
            "lva_code":       None,
        }

        result.append({"content": raw, "metadata": meta})

    return result


# ─────────────────────────────────────────────────────────────────────────────
# ÖFFENTLICHE API
# ─────────────────────────────────────────────────────────────────────────────

def chunk_curriculum_pdf(
    pdf_bytes:     bytes,
    degree:        str,
    study_program: str,
) -> list[dict]:
    """
    Hauptfunktion: Verarbeitet ein Curriculum-PDF und gibt eine Liste von
    Chunks mit Web-Chunk-kompatiblen Metadaten zurück.

    Jeder Chunk ist ein dict:
      {
        "content":  str,   # Text für Embedding
        "metadata": dict,  # Web-Chunk-kompatible Metadaten
      }

    :param pdf_bytes:     Rohe PDF-Bytes
    :param degree:        z.B. "Bachelor" oder "Master"
    :param study_program: z.B. "Wirtschaftsinformatik"
    :returns:             Liste von Chunk-Dicts, bereit für Embedding + Supabase-Insert
    """
    all_chunks: list[dict] = []
    current_section = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            raw_text = page.extract_text() or ""

            # Inhaltsverzeichnis-Seiten überspringen
            if raw_text.count(_TOC_MARKER) > _TOC_THRESHOLD:
                continue

            # Aktuellen §-Abschnitt aus Seitentext ermitteln
            section = _detect_section_context(raw_text, current_section)
            current_section = section

            # ── Echte Tabellen (lines_strict) zuerst ─────────────────────
            tables = page.find_tables(table_settings=TABLE_SETTINGS_LINES)

            processed_table_regions = []  # BBoxen der Tabellen merken

            for t_idx, table_obj in enumerate(tables):
                table_data = table_obj.extract()
                if not table_data or not table_data[0]:
                    continue

                # Übersichtstabellen ohne Code (z.B. Seite 7: nur Bezeichnung+ECTS)
                # → als einzelnen Übersichts-Prose-Chunk, nicht zeilenweise
                if _is_overview_table(table_data):
                    overview_text = _overview_table_to_text(table_data, section, degree, study_program)
                    if overview_text:
                        all_chunks.append({
                            "content": overview_text,
                            "metadata": {
                                "ects": None, "degree": degree, "lva_name": None,
                                "has_table": True, "chunk_type": "overview_table",
                                "source_url": None, "course_name": None,
                                "course_type": None, "module_name": None,
                                "source_type": "curriculum_pdf",
                                "study_program": study_program,
                                "overview_level": "fach",
                                "section": section, "lva_code": None,
                            }
                        })
                    processed_table_regions.append(table_obj.bbox)
                    continue

                # Text direkt über dieser Tabelle für module_name-Erkennung
                x0, top, x1, bottom = table_obj.bbox
                text_above = ""
                if top > 0:
                    try:
                        region = page.crop((0, 0, page.width, top))
                        text_above = region.extract_text() or ""
                    except Exception:
                        text_above = raw_text

                module_name = _detect_module_context(text_above)

                table_chunks = _chunks_from_table(
                    table_data,
                    section=section,
                    module_name=module_name,
                    degree=degree,
                    study_program=study_program,
                )
                all_chunks.extend(table_chunks)
                processed_table_regions.append(table_obj.bbox)

            # ── Fließtext (Bereiche außerhalb der Tabellen) ───────────────
            # Text der Seite, aber ohne die bereits verarbeiteten Tabellenbereiche
            prose_text = _extract_prose_only(page, processed_table_regions, raw_text)

            prose_chunks = _chunks_from_prose(
                prose_text,
                section=section,
                degree=degree,
                study_program=study_program,
            )
            all_chunks.extend(prose_chunks)

    # Chunk-Index nachträglich setzen
    for i, chunk in enumerate(all_chunks):
        chunk["metadata"]["chunk_index"] = i

    return all_chunks


def _extract_prose_only(page, table_bboxes: list, fallback_text: str) -> str:
    """
    Extrahiert nur den Fließtext einer Seite, ohne die Tabellenbereiche.

    Für Seiten ohne Tabellen wird der rohe Seitentext zurückgegeben.
    Für Seiten mit Tabellen werden die entsprechenden Regionen ausgeschnitten.
    """
    if not table_bboxes:
        return fallback_text

    parts = []
    prev_bottom = 0

    for bbox in sorted(table_bboxes, key=lambda b: b[1]):
        x0, top, x1, bottom = bbox
        if top > prev_bottom:
            region = page.crop((0, prev_bottom, page.width, top))
            text = region.extract_text()
            if text and text.strip():
                parts.append(text)
        prev_bottom = bottom

    # Text nach der letzten Tabelle
    if prev_bottom < page.height:
        region = page.crop((0, prev_bottom, page.width, page.height))
        text = region.extract_text()
        if text and text.strip():
            parts.append(text)

    return "\n\n".join(parts)