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
    Parst mehrzeilige Tabellenzellen und löst das JKU-spezifische Verschiebungsproblem.
    Verhindert einen Off-by-One-Fehler, indem Kategorie-Labels (z.B. Basiskompetenz)
    isoliert und mehrzeilige Kursbezeichnungen intelligent zusammengeführt werden.
    """
    if not table_data or len(table_data) < 2:
        return []

    header = [str(h or "").strip() for h in table_data[0]]

    # 1. Zeilenumbruch-getrennte Zellwerte spaltenweise aggregieren
    col_values = [[] for _ in header]
    for row_idx in range(1, len(table_data)):
        for col_idx in range(len(header)):
            cell = table_data[row_idx][col_idx] if col_idx < len(table_data[row_idx]) else ""
            parts = str(cell or "").split("\n")
            col_values[col_idx].extend(parts)

    col_values = [[v.strip() for v in col] for col in col_values]

    # 2. Key-Spalte 'Bezeichnung' für die strukturelle Ausrichtung identifizieren
    bez_col = None
    for i, h in enumerate(header):
        if "bezeichnung" in h.lower():
            bez_col = i
            break

    if bez_col is None:
        # Fallback-Index-Zip falls kein eindeutiger Header existiert
        max_rows = max(len(col) for col in col_values) if col_values else 0
        rows = []
        for i in range(max_rows):
            row = {}
            for col_idx, col_name in enumerate(header):
                vals = col_values[col_idx]
                row[col_name] = vals[i] if i < len(vals) else ""
            rows.append(row)
        return rows

    # 3. Spaltenwerte in 'Bezeichnung' und 'Andere' splitten
    bez_entries_raw = col_values[bez_col]
    other_col_indices = [i for i in range(len(header)) if i != bez_col]

    other_values = {}
    for ci in other_col_indices:
        other_values[ci] = [v for v in col_values[ci] if v]

    # Maximale Anzahl an Datenzeilen anhand der Metadaten-Spalten (Code/ECTS) ermitteln
    n_target = max(len(vals) for vals in other_values.values()) if other_values else 0

    # 4. Echte Lehrveranstaltungen von reinen Tabellen-Zwischenüberschriften trennen
    actual_entries = []   # (original_index, bezeichnung)
    category_entries = [] # (original_index, bezeichnung)

    for i, bez in enumerate(bez_entries_raw):
        if not bez:
            continue
        if bez in CATEGORY_LABELS:
            category_entries.append((i, bez))
        else:
            actual_entries.append((i, bez))

    # 5. Fortsetzungszeilen (Multiline-Zellen ohne eigenen Code) beim Vorgänger anfügen
    if n_target > 0 and len(actual_entries) > n_target:
        merged = []
        j = 0
        while j < len(actual_entries):
            idx, name = actual_entries[j]
            j += 1
            remaining_codes = n_target - len(merged) - 1
            remaining_bez = len(actual_entries) - j
            # Falls mehr Bezeichnungen als Codes übrig sind -> Textzeilen mergen
            while remaining_bez > remaining_codes and j < len(actual_entries):
                _, continuation = actual_entries[j]
                name += " " + continuation
                j += 1
                remaining_bez = len(actual_entries) - j
            merged.append((idx, name))
        actual_entries = merged

    # 6. Iteratoren für synchronisiertes Zusammensetzen aufsetzen
    other_iters = {ci: iter(other_values[ci]) for ci in other_col_indices}

    # Einträge anhand ihrer ursprünglichen PDF-Position sortieren, um die Reihenfolge zu wahren
    all_entries = [(pos, "category", val) for pos, val in category_entries]
    all_entries += [(pos, "data", val) for pos, val in actual_entries]
    all_entries.sort(key=lambda x: x[0])

    # 7. Finales Zeilen-Dictionary aufbauen
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
    Erkennt reine tabellarische Gesamtübersichten (z.B. Zuordnung der Fächer zu ECTS), 
    denen eine konkrete 'Code'- bzw. 'Studienfachkennung'-Spalte fehlt.
    """
    if not table_data or not table_data[0]:
        return False
    header = [str(h or "").strip().lower() for h in table_data[0]]
    has_code = any(h in ("code", "studienfachkennung") for h in header)
    return not has_code


def _is_semester_table(table_data: list) -> bool:
    """
    Erkennt Tabellen, die den empfohlenen bzw. idealtypischen Studienverlauf 
    nach Semestern strukturiert abbilden.
    """
    if not table_data or not table_data[0]:
        return False
    first_cell = str(table_data[0][0] or "").strip()
    return bool(re.match(r'\d+\.\s*Semester', first_cell))


def _is_section_header_row(row: dict) -> bool:
    """
    Identifiziert Zeilen, die als interne Trenner fungieren (z.B. 'Gesamt', 
    'Basiskompetenz'), um die Erzeugung von wertlosen Pseudo-Kurs-Chunks zu verhindern.
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
    Durchsucht den gesamten Rohtext einer Seite nach Paragraphen-Zeichen (§) 
    und liefert den letzten Treffer als aktuellen Kontext zurück.
    """
    last_found = prev_section
    for line in page_text.splitlines():
        line = line.strip()
        if re.match(r'^§\s*\d+[a-z]?\s+\S', line):
            last_found = line
    return last_found


def _extract_section_heading(text: str) -> Optional[str]:
    """
    Extrahiert eine valide §-Überschrift aus einem Text-Chunk und bereinigt diese 
    von Klammern, Rändern oder Absatznummerierungen.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('['):
            line = line.lstrip('[').rstrip(']').strip()
        m = re.match(r'(§\s*\d+[a-z]?\s+[A-ZÄÖÜ][\w\s,\-&]*)', line)
        if m:
            heading = m.group(1).strip()
            heading = re.split(r'\s*\(\d+\)', heading)[0].strip()
            return heading
    return None


def _detect_module_context(text_before_table: str) -> str:
    """
    Analysiert das Textsegment direkt oberhalb einer Tabelle (letzte 200 Zeichen) 
    nach der JKU-typischen Einleitungsphrase für Modul- und Fachbezeichnungen.
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
    Transformiert eine tabelarische Gesamtübersicht (Fach + ECTS) in einen Fließtext-Block 
    und gleicht dabei fehlende Zellen-Offsets bei Kategorie-Trennern aus.
    """
    if not table_data or len(table_data) < 2:
        return ""

    bez_list  = str(table_data[1][0] or "").split("\n")
    ects_list = str(table_data[1][1] or "").split("\n") if len(table_data[1]) > 1 else []

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
    Konvertiert eine Semester-Verlaufstabelle in ein textuelles Format und befüllt 
    die Metadaten mit dem spezifischen 'semester_plan'-Typ für das Web-UI.
    """
    if not table_data or not table_data[0]:
        return None

    semester_name = str(table_data[0][0] or "").strip()

    lines = [
        f"Studium: {study_program}. Typ: {degree}. Abschnitt: {section}.",
        f"Idealtypischer Studienverlauf, {semester_name}:"
    ]

    for row_idx in range(1, len(table_data)):
        row = table_data[row_idx]
        bez_raw  = str(row[0] or "").strip() if len(row) > 0 else ""
        ects_raw = str(row[1] or "").strip() if len(row) > 1 else ""

        # Rekursives Splitten, falls die Semesterdaten unaufgetrennt als Multiline-Block geliefert werden
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
    Erzeugt aus einer Detail-Tabelle (LVA-Ebene) für jede extrahierte Zeile 
    einen hochgradig strukturierten Key-Value-Text-Chunk für das Vektormodell.
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

        # Erzeugung des standardisierten, Suchmodell-optimierten Textformats
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
    Extrahiert reguläre Textblöcke und rechtliche Bestimmungen. Überwacht dabei 
    während der Iteration Überschriften-Wechsel, um Chunks granulär zu labeln.
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

        # In-Chunk-Validierung: Überschriften-Kontext bei Paragraphen-Wechsel mittendrin updaten
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
    Hauptfunktion: Orchestriert den gesamten Parsing-Prozess des JKU-Curriculums.
    Trennt Tabellen von Prosa, sichert seitenübergreifenden Kontext und injiziert Meta-Indizes.
    """
    all_chunks: list[dict] = []
    current_section = ""
    prev_text_end = ""  # Sichert den Text-Kontext der Vorseite bei seitenübergreifenden Modulen

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            raw_text = page.extract_text() or ""

            # Inhaltsverzeichnisse über Punkt-Muster-Frequenz erkennen und überspringen
            if raw_text.count(_TOC_MARKER) > _TOC_THRESHOLD:
                prev_text_end = raw_text[-200:] if raw_text else ""
                continue

            # Rechtlichen Paragraph-Kontext bestimmen
            section = _detect_section_context(raw_text, current_section)
            current_section = section

            # ── Echte Tabellen (lines_strict) zuerst verarbeiten ─────────────────────
            tables = page.find_tables(table_settings=TABLE_SETTINGS_LINES)
            processed_table_regions = []

            for t_idx, table_obj in enumerate(tables):
                table_data = table_obj.extract()
                if not table_data or not table_data[0]:
                    continue

                # Typ-Weiche 1: Semesterpläne extrahieren
                if _is_semester_table(table_data):
                    chunk = _semester_table_to_chunk(
                        table_data, section, degree, study_program
                    )
                    if chunk:
                        all_chunks.append(chunk)
                    processed_table_regions.append(table_obj.bbox)
                    continue

                # Typ-Weiche 2: Übergeordnete Fach-Übersichtstabellen verarbeiten
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

                # Typ-Weiche 3: Detaillierte LVA-Tabellen parsen
                x0, top, x1, bottom = table_obj.bbox
                text_above = ""
                if top > 0:
                    try:
                        region = page.crop((0, 0, page.width, top))
                        text_above = region.extract_text() or ""
                    except Exception:
                        text_above = raw_text

                # Modulbezeichnung im Textbereich oberhalb oder auf der Vorseite detektieren
                module_name = _detect_module_context(text_above)
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

            # ── Fließtext extrahieren (Bereiche außerhalb bereits geparster Tabellen) ──
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

            # Historie für die darauffolgende Seite puffern
            prev_text_end = raw_text[-200:] if raw_text else ""

    # Globalen, fortlaufenden Chunk-Index über alle Generate hinweg setzen
    for i, chunk in enumerate(all_chunks):
        chunk["metadata"]["chunk_index"] = i

    return all_chunks


def _extract_prose_only(page, table_bboxes: list, fallback_text: str) -> str:
    """
    Schneidet die erkannten Tabellen-Bounding-Boxes (Bboxes) geometrisch aus der PDF-Seite 
    heraus, um Textdopplungen in Fließtext-Chunks sauber zu verhindern.
    """
    if not table_bboxes:
        return fallback_text

    parts = []
    prev_bottom = 0

    # Sortiertes vertikales Cropping zwischen den Tabellen-Grenzen
    for bbox in sorted(table_bboxes, key=lambda b: b[1]):
        x0, top, x1, bottom = bbox
        if top > prev_bottom:
            region = page.crop((0, prev_bottom, page.width, top))
            text = region.extract_text()
            if text and text.strip():
                parts.append(text)
        prev_bottom = bottom

    # Letzten Absatz nach der letzten Tabelle sichern
    if prev_bottom < page.height:
        region = page.crop((0, prev_bottom, page.width, page.height))
        text = region.extract_text()
        if text and text.strip():
            parts.append(text)

    return "\n\n".join(parts)