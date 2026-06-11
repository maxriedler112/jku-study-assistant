"""
pdf_chunking.py – Spezialisiertes Chunking für JKU Curriculum-PDFs.
====================================================================

Erzeugt Chunks mit Web-Chunk-kompatiblen Metadaten, damit das Retrieval-
Modell PDF- und Web-Chunks gleich gut durchsuchen und kombinieren kann.

STRATEGIE:
  1. Echte Tabellen (lines_strict) → pro Zeile ein strukturierter Chunk
     mit Metadaten: course_name, ects, code, module_name, section, degree
  2. Semester-Tabellen (idealtypischer Studienverlauf) → lesbarer Chunk
     pro Semester mit allen LVAs und ECTS
  3. Übersichtstabellen (nur Bezeichnung+ECTS) → Gesamtübersicht als Chunk
  4. Fließtext (§-Absätze) → Contextual Chunks mit section_heading als
     Kontext-Header (identisch zur bestehenden chunking.py-Logik)

ÄNDERUNGEN GEGENÜBER V1:
  - FIX: Off-by-one in Haupttabelle (Basiskompetenz/Kernkompetenz-Labels
    existieren nur in Bezeichnung, nicht in Code/ECTS → Alignment-Fix)
  - FIX: Multiline-Kursnamen ("Managements" als Fortsetzungszeile) werden
    mit der vorherigen Zeile zusammengeführt
  - FIX: module_name-Erkennung über Seitengrenzen hinweg (prev_text_end)
  - FIX: Semester-Tabellen (idealtypischer Studienverlauf) werden erkannt
    und als eigene Chunks mit Semester-Kontext ausgegeben
  - FIX: Section-Labels werden pro Prose-Chunk aktualisiert statt pro Seite

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

_TOC_MARKER = ". ."
_TOC_THRESHOLD = 8

# Kategorie-Labels die NUR in der Bezeichnung-Spalte existieren,
# aber KEINE eigene Zeile in Code/ECTS haben
CATEGORY_LABELS = {"Basiskompetenz", "Kernkompetenz"}


# ─────────────────────────────────────────────────────────────────────────────
# HILFSFUNKTIONEN: Tabellen-Parsing
# ─────────────────────────────────────────────────────────────────────────────

def _expand_multiline_cells(table_data: list) -> list[dict]:
    """
    Expandiert mehrzeilige Zellen aus pdfplumber zu separaten Zeilen.

    KRITISCHER FIX gegenüber V1:
    Kategorie-Labels (Basiskompetenz, Kernkompetenz) existieren NUR in der
    Bezeichnung-Spalte. Code- und ECTS-Spalten haben keine entsprechenden
    Einträge. Die V1-Version hat blind nach Index gezippt → alles war um
    1-2 Positionen verschoben.

    Neuer Ansatz:
    1. Bezeichnung-Spalte splitten, Kategorien identifizieren
    2. Nur Nicht-Kategorie-Einträge mit Code/ECTS paaren
    3. Wenn Bezeichnung trotzdem mehr Einträge hat als Code → das sind
       Fortsetzungszeilen (z.B. "Managements") → mit Vorgänger mergen
    """
    if not table_data or len(table_data) < 2:
        return []

    header = [str(h or "").strip() for h in table_data[0]]

    # Alle Zell-Werte sammeln (über alle Datenzeilen hinweg, \n splitten)
    col_values = [[] for _ in header]
    for row_idx in range(1, len(table_data)):
        for col_idx in range(len(header)):
            cell = table_data[row_idx][col_idx] if col_idx < len(table_data[row_idx]) else ""
            parts = str(cell or "").split("\n")
            col_values[col_idx].extend(parts)

    col_values = [[v.strip() for v in col] for col in col_values]

    # ── Bezeichnung-Spalte finden ────────────────────────────────────────
    bez_col = None
    for i, h in enumerate(header):
        if "bezeichnung" in h.lower():
            bez_col = i
            break

    if bez_col is None:
        # Kein Bezeichnung-Header → einfacher Index-Zip (Fallback)
        max_rows = max(len(col) for col in col_values) if col_values else 0
        rows = []
        for i in range(max_rows):
            row = {}
            for col_idx, col_name in enumerate(header):
                vals = col_values[col_idx]
                row[col_name] = vals[i] if i < len(vals) else ""
            rows.append(row)
        return rows

    # ── Spalten aufteilen ────────────────────────────────────────────────
    bez_entries_raw = col_values[bez_col]
    other_col_indices = [i for i in range(len(header)) if i != bez_col]

    # Nicht-leere Werte aus den anderen Spalten (Code, ECTS)
    other_values = {}
    for ci in other_col_indices:
        other_values[ci] = [v for v in col_values[ci] if v]

    # Anzahl der echten Datenzeilen = max(len) der Nicht-Bezeichnung-Spalten
    n_target = max(len(vals) for vals in other_values.values()) if other_values else 0

    # ── Kategorien separieren ────────────────────────────────────────────
    actual_entries = []   # (original_index, bezeichnung)
    category_entries = [] # (original_index, bezeichnung)

    for i, bez in enumerate(bez_entries_raw):
        if not bez:
            continue
        if bez in CATEGORY_LABELS:
            category_entries.append((i, bez))
        else:
            actual_entries.append((i, bez))

    # ── Fortsetzungszeilen mergen ────────────────────────────────────────
    # Wenn actual_entries mehr Einträge hat als n_target, sind überschüssige
    # Einträge Fortsetzungszeilen (z.B. "Managements") → mit Vorgänger mergen
    if n_target > 0 and len(actual_entries) > n_target:
        merged = []
        j = 0
        while j < len(actual_entries):
            idx, name = actual_entries[j]
            j += 1
            # Solange es noch mehr Bezeichnungen als verbleibende Codes gibt
            remaining_codes = n_target - len(merged) - 1
            remaining_bez = len(actual_entries) - j
            while remaining_bez > remaining_codes and j < len(actual_entries):
                _, continuation = actual_entries[j]
                name += " " + continuation
                j += 1
                remaining_bez = len(actual_entries) - j
            merged.append((idx, name))
        actual_entries = merged

    # ── Iteratoren für Nicht-Bezeichnung-Spalten ─────────────────────────
    other_iters = {ci: iter(other_values[ci]) for ci in other_col_indices}

    # ── Ergebnis zusammenbauen ───────────────────────────────────────────
    # Kategorien und Datenzeilen nach Originalposition sortieren
    all_entries = [(pos, "category", val) for pos, val in category_entries]
    all_entries += [(pos, "data", val) for pos, val in actual_entries]
    all_entries.sort(key=lambda x: x[0])

    rows = []
    for pos, entry_type, val in all_entries:
        row = {header[bez_col]: val}
        if entry_type == "category":
            for ci in other_col_indices:
                row[header[ci]] = ""
        else:
            for ci in other_col_indices:
                row[header[ci]] = next(other_iters[ci], "")
        rows.append(row)

    return rows


def _is_overview_table(table_data: list) -> bool:
    """
    Erkennt Übersichtstabellen ohne Code-Spalte (z.B. die Gesamtübersicht
    auf Seite 7: nur 'Bezeichnung' + 'ECTS', kein 'Code'/'Studienfachkennung').
    """
    if not table_data or not table_data[0]:
        return False
    header = [str(h or "").strip().lower() for h in table_data[0]]
    has_code = any(h in ("code", "studienfachkennung") for h in header)
    return not has_code


def _is_semester_table(table_data: list) -> bool:
    """
    Erkennt Semester-Tabellen (idealtypischer Studienverlauf).
    Diese haben im Header "N. Semester (WS/SS)" oder ähnlich.
    """
    if not table_data or not table_data[0]:
        return False
    first_cell = str(table_data[0][0] or "").strip()
    return bool(re.match(r'\d+\.\s*Semester', first_cell))


def _is_section_header_row(row: dict) -> bool:
    """
    Erkennt Zwischenüberschriften in ECTS-Tabellen wie 'Basiskompetenz' oder
    'Kernkompetenz', die keine echten Kurszeilen sind.
    """
    ects = row.get("ECTS", "").strip()
    bez  = row.get("Bezeichnung", "").strip()
    code = row.get("Code", row.get("Studienfachkennung", "")).strip()

    if not ects and not code:
        return True
    if bez.lower() == "gesamt":
        return True
    if bez in CATEGORY_LABELS:
        return True

    return False


def _detect_section_context(page_text: str, prev_section: str) -> str:
    """
    Erkennt die aktuelle §-Überschrift aus dem Seitenrohtext.

    FIX: Scannt jetzt den gesamten Seitentext (nicht nur erste 10 Zeilen)
    und gibt die LETZTE gefundene § zurück. Das sorgt dafür, dass auf Seiten
    mit mehreren §§ zumindest die Section-Erkennung für den Großteil stimmt.
    """
    last_found = prev_section
    for line in page_text.splitlines():
        line = line.strip()
        if re.match(r'^§\s*\d+[a-z]?\s+\S', line):
            last_found = line
    return last_found


def _extract_section_heading(text: str) -> Optional[str]:
    """
    Extrahiert eine §-Überschrift aus einem Textblock.
    Gibt z.B. "§ 12 Prüfungsordnung" zurück, oder None.
    """
    for line in text.splitlines():
        line = line.strip()
        # Kontext-Klammern entfernen falls vorhanden
        if line.startswith('['):
            line = line.lstrip('[').rstrip(']').strip()
        m = re.match(r'(§\s*\d+[a-z]?\s+[A-ZÄÖÜ][\w\s,\-&]*)', line)
        if m:
            heading = m.group(1).strip()
            # Abschneiden bei Klammern oder Absatznummern
            heading = re.split(r'\s*\(\d+\)', heading)[0].strip()
            return heading
    return None


def _detect_module_context(text_before_table: str) -> str:
    """
    Findet den zugehörigen Modul-/Fach-Namen aus dem Text DIREKT VOR einer Tabelle.
    Sucht nur in den letzten 200 Zeichen.
    """
    relevant = text_before_table[-200:] if len(text_before_table) > 200 else text_before_table
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

    Behandelt den pdfplumber-Offset bei Kategorie-Labels:
    Basiskompetenz/Kernkompetenz haben keine eigene ECTS-Zelle.
    """
    if not table_data or len(table_data) < 2:
        return ""

    # Rohe Zell-Listen direkt aus pdfplumber
    bez_list  = str(table_data[1][0] or "").split("\n")
    ects_list = str(table_data[1][1] or "").split("\n") if len(table_data[1]) > 1 else []

    # Bezeichnungen ohne Kategorie-Labels → echte Fächer
    faecher = [b.strip() for b in bez_list
               if b.strip() and b.strip().lower() not in {c.lower() for c in CATEGORY_LABELS}]

    lines = [f"Studium: {study_program}. Typ: {degree}. Abschnitt: {section}."]
    lines.append("ECTS-Übersicht:")

    for i, bez in enumerate(faecher):
        if bez.lower() in ("gesamt", "freie studienleistungen"):
            continue
        ects = ects_list[i].strip() if i < len(ects_list) else ""
        if bez and ects:
            lines.append(f"  {bez}: {ects} ECTS")

    lines.append("  Gesamt: 180 ECTS")

    return "\n".join(lines) if len(lines) > 2 else ""


def _semester_table_to_chunk(
    table_data:    list,
    section:       str,
    degree:        str,
    study_program: str,
) -> Optional[dict]:
    """
    Wandelt eine Semester-Tabelle (idealtypischer Studienverlauf) in einen
    lesbaren Chunk.

    Semester-Tabellen haben den Header z.B. "1. Semester (WS) | ECTS"
    und enthalten einzelne LVAs mit ECTS-Werten.

    Gibt einen Chunk-Dict zurück oder None bei leerem Ergebnis.
    """
    if not table_data or not table_data[0]:
        return None

    semester_name = str(table_data[0][0] or "").strip()

    lines = [
        f"Studium: {study_program}. Typ: {degree}. Abschnitt: {section}.",
        f"Idealtypischer Studienverlauf, {semester_name}:"
    ]

    # Datenzeilen können als separate Rows ODER als multiline-Cell kommen
    for row_idx in range(1, len(table_data)):
        row = table_data[row_idx]
        bez_raw  = str(row[0] or "").strip() if len(row) > 0 else ""
        ects_raw = str(row[1] or "").strip() if len(row) > 1 else ""

        # Multiline-Cells expandieren
        if "\n" in bez_raw or "\n" in ects_raw:
            bez_parts  = bez_raw.split("\n")
            ects_parts = ects_raw.split("\n")
            for i, b in enumerate(bez_parts):
                b = b.strip()
                e = ects_parts[i].strip() if i < len(ects_parts) else ""
                if not b:
                    continue
                if b.lower() == "summe":
                    lines.append(f"  Summe: {e} ECTS")
                elif b and e:
                    lines.append(f"  {b}: {e} ECTS")
        else:
            if not bez_raw:
                continue
            if bez_raw.lower() == "summe":
                lines.append(f"  Summe: {ects_raw} ECTS")
            elif bez_raw and ects_raw:
                lines.append(f"  {bez_raw}: {ects_raw} ECTS")

    if len(lines) <= 2:
        return None

    content = "\n".join(lines)

    return {
        "content": content,
        "metadata": {
            "ects":           None,
            "degree":         degree,
            "lva_name":       None,
            "has_table":      True,
            "chunk_type":     "semester_plan",
            "source_url":     None,
            "course_name":    None,
            "course_type":    None,
            "module_name":    None,
            "source_type":    "curriculum_pdf",
            "study_program":  study_program,
            "overview_level": "semester",
            "section":        section,
            "lva_code":       None,
            "semester_label": semester_name,
        }
    }


def _chunks_from_table(
    table_data:    list,
    section:       str,
    module_name:   str,
    degree:        str,
    study_program: str,
) -> list[dict]:
    """
    Erzeugt pro Kurszeile einen strukturierten Chunk + Metadaten.
    Nutzt die gefixte _expand_multiline_cells().
    """
    rows = _expand_multiline_cells(table_data)
    chunks = []

    current_category = ""

    for row in rows:
        bez  = row.get("Bezeichnung", "").strip()
        ects = row.get("ECTS", "").strip()
        code = row.get("Code", row.get("Studienfachkennung", "")).strip()

        if bez in CATEGORY_LABELS:
            current_category = bez
            continue

        if _is_section_header_row(row) or not bez:
            continue

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

    FIX: Section-Label wird jetzt PRO CHUNK aktualisiert. Wenn ein Chunk
    eine neue §-Überschrift enthält, wird ab dort die neue Section verwendet.
    """
    from chunking import clean_text, chunk_text

    cleaned = clean_text(page_text)
    if not cleaned.strip():
        return []

    raw_chunks = chunk_text(cleaned)
    result = []
    running_section = section

    for raw in raw_chunks:
        if len(raw.strip()) < 40:
            continue

        # Prüfen ob dieser Chunk eine neue § enthält
        found_section = _extract_section_heading(raw)
        if found_section:
            running_section = found_section

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
            "section":        running_section,
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
    """
    all_chunks: list[dict] = []
    current_section = ""
    prev_text_end = ""  # FIX: Letzten Text der vorherigen Seite merken

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            raw_text = page.extract_text() or ""

            # Inhaltsverzeichnis-Seiten überspringen
            if raw_text.count(_TOC_MARKER) > _TOC_THRESHOLD:
                prev_text_end = raw_text[-200:] if raw_text else ""
                continue

            # Aktuellen §-Abschnitt ermitteln (scannt jetzt ganze Seite)
            section = _detect_section_context(raw_text, current_section)
            current_section = section

            # ── Echte Tabellen (lines_strict) zuerst ─────────────────────
            tables = page.find_tables(table_settings=TABLE_SETTINGS_LINES)
            processed_table_regions = []

            for t_idx, table_obj in enumerate(tables):
                table_data = table_obj.extract()
                if not table_data or not table_data[0]:
                    continue

                # ── 1. Semester-Tabellen ─────────────────────────────────
                if _is_semester_table(table_data):
                    chunk = _semester_table_to_chunk(
                        table_data, section, degree, study_program
                    )
                    if chunk:
                        all_chunks.append(chunk)
                    processed_table_regions.append(table_obj.bbox)
                    continue

                # ── 2. Übersichtstabellen (nur Bezeichnung+ECTS) ────────
                if _is_overview_table(table_data):
                    overview_text = _overview_table_to_text(
                        table_data, section, degree, study_program
                    )
                    if overview_text:
                        all_chunks.append({
                            "content": overview_text,
                            "metadata": {
                                "ects": None, "degree": degree,
                                "lva_name": None, "has_table": True,
                                "chunk_type": "overview_table",
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

                # ── 3. Detail-Tabellen (Code + Bezeichnung + ECTS) ──────
                x0, top, x1, bottom = table_obj.bbox
                text_above = ""
                if top > 0:
                    try:
                        region = page.crop((0, 0, page.width, top))
                        text_above = region.extract_text() or ""
                    except Exception:
                        text_above = raw_text

                module_name = _detect_module_context(text_above)

                # FIX: Wenn kein Modul auf dieser Seite gefunden, Text
                # vom Ende der vorherigen Seite prüfen
                if not module_name and prev_text_end:
                    module_name = _detect_module_context(prev_text_end)

                table_chunks = _chunks_from_table(
                    table_data,
                    section=section,
                    module_name=module_name,
                    degree=degree,
                    study_program=study_program,
                )
                all_chunks.extend(table_chunks)
                processed_table_regions.append(table_obj.bbox)

            # ── Fließtext (außerhalb der Tabellen) ────────────────────────
            prose_text = _extract_prose_only(
                page, processed_table_regions, raw_text
            )

            prose_chunks = _chunks_from_prose(
                prose_text,
                section=section,
                degree=degree,
                study_program=study_program,
            )
            all_chunks.extend(prose_chunks)

            # FIX: Seitentext für Cross-Page-Kontext merken
            prev_text_end = raw_text[-200:] if raw_text else ""

    # Chunk-Index nachträglich setzen
    for i, chunk in enumerate(all_chunks):
        chunk["metadata"]["chunk_index"] = i

    return all_chunks


def _extract_prose_only(page, table_bboxes: list, fallback_text: str) -> str:
    """
    Extrahiert nur den Fließtext einer Seite, ohne die Tabellenbereiche.
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

    if prev_bottom < page.height:
        region = page.crop((0, prev_bottom, page.width, page.height))
        text = region.extract_text()
        if text and text.strip():
            parts.append(text)

    return "\n\n".join(parts)