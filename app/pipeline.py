"""
pipeline.py – Zentrale ETL-Pipeline des JKU Study Assistants.
==============================================================

Diese Datei ist das Herzstück der Datenvorbereitung. Sie nimmt eine PDF-Datei
entgegen und führt alle Schritte durch, die nötig sind, damit das KI-Modell
später sinnvolle Antworten liefern kann:

  PDF-Bytes  →  Supabase Storage (Backup der Originaldatei)
             →  Seitenweise Text- & Tabellen-Extraktion (pdfplumber)
                  • detect_two_column_layout() erkennt zweispaltige Seiten
                  • extract_page_content() kombiniert Text und Tabellen
                    in der richtigen Lesereihenfolge (oben → unten)
                  • find_tables() liefert exakte Positionen (Bounding-Boxes)
                  • crop() extrahiert Text NUR aus tabellenfreien Bereichen
                  • table_to_markdown() wandelt Tabellen in lesbares Format um,
                    inklusive Forward-Fill bei zusammengeführten Zellen
             →  Chunking (chunking.py) – Text in sinnvolle Abschnitte teilen
             →  Embeddings (embeddings.py / E5-Modell) – Text → Zahlenvektor
             →  Chunks + Metadaten in Supabase speichern

ICS-Bytes   →  Kalender-Events parsen  →  Supabase (ingest_ics.py)

Abhängigkeiten:
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

# ── Umgebungsvariablen laden (.env Datei) ────────────────────────────────────
# Die .env Datei enthält geheime Schlüssel (API-Keys, Datenbank-URLs).
# Sie darf NIEMALS in Git eingecheckt werden!
load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise ValueError("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt in der .env Datei")

# Supabase-Client mit Service-Role-Key.
# Der Service-Role-Key hat Admin-Rechte und umgeht Row-Level-Security (RLS).
# Nur für serverseitige Operationen verwenden – nie im Frontend!
supabase: Client = create_client(url, key)

# Name des Supabase-Storage-Buckets, in dem die Original-PDFs gespeichert werden.
BUCKET = "documents"

# ── Tabellen-Erkennungseinstellungen ─────────────────────────────────────────
# pdfplumber kann Tabellen auf zwei Arten erkennen:
#   "lines_strict" → sucht nach echten Linien im PDF (für Tabellen mit Rahmen)
#   "text"         → erkennt Tabellen anhand von Textabständen (für linienlose Tabellen)
#
# Viele JKU-Curricula haben Tabellen MIT Rahmenlinien → TABLE_SETTINGS_LINES
# Manche Seiten haben tabellenartige Layouts OHNE Linien → TABLE_SETTINGS_TEXT
#
# extract_page_content() versucht zuerst die strenge Variante und fällt bei
# Misserfolg automatisch auf die Text-basierte zurück.

TABLE_SETTINGS_LINES = {
    # Strategie für vertikale Linien: nur echte PDF-Linien verwenden
    "vertical_strategy":   "lines_strict",
    # Strategie für horizontale Linien: nur echte PDF-Linien verwenden
    "horizontal_strategy": "lines_strict",
    # Toleranz in Punkten, um leicht versetzte Linien zusammenzuführen
    "snap_tolerance":      5,
    # Toleranz zum Zusammenfügen unterbrochener Linien
    "join_tolerance":      3,
    # Mindestlänge einer Linie, damit sie als Tabellenrahmen gilt (in Punkten)
    "edge_min_length":     10,
}

TABLE_SETTINGS_TEXT = {
    # Spalten werden anhand von Textpositionen erkannt (kein Linien-Erfordernis)
    "vertical_strategy":   "text",
    # Zeilen werden anhand von Textpositionen erkannt
    "horizontal_strategy": "text",
    # Etwas höhere Toleranz, da Textabstände ungenauer sind als Linien
    "snap_tolerance":      8,
    "join_tolerance":      5,
    "edge_min_length":     10,
}


# ═══════════════════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN – PDF-Parsing
# ═══════════════════════════════════════════════════════════════════════════════

def table_to_markdown(table: list) -> str:
    """
    Wandelt eine pdfplumber-Tabelle in einen Markdown-Tabellenstring um.

    WAS IST DAS PROBLEM MIT ROHEN TABELLENDATEN?
      pdfplumber gibt Tabellen als Liste von Zeilen zurück, jede Zeile ist
      eine Liste von Zellen. Bei zusammengeführten Zellen (Merged Cells) –
      z.B. eine Überschrift die über 3 Spalten geht – gibt pdfplumber None
      für die leeren Folgezellen zurück.

      Altes Verhalten:  None → "" → leere Zelle im Output → Kontext geht verloren
      Neues Verhalten:  None → Wert der letzten nicht-leeren Zelle in der Spalte
                        (Forward-Fill) → Kontext bleibt erhalten

    BEISPIEL:
      Eingabe (raw):
        [["Pflichtfächer (Bachelor)", None,   None  ],
         ["Mathematik",               "4",    "VL"  ],
         ["Algorithmen",              "3",    "VL"  ]]

      Nach Forward-Fill:
        [["Pflichtfächer (Bachelor)", "Pflichtfächer (Bachelor)", "Pflichtfächer (Bachelor)"],
         ["Mathematik",               "4",    "VL"  ],
         ["Algorithmen",              "3",    "VL"  ]]

      Markdown-Output:
        | Pflichtfächer (Bachelor) | Pflichtfächer (Bachelor) | Pflichtfächer (Bachelor) |
        | --- | --- | --- |
        | Mathematik | 4 | VL |
        | Algorithmen | 3 | VL |

    :param table: Liste von Zeilen (aus pdfplumber table_obj.extract())
    :returns:     Fertig formatierter Markdown-String, oder "" bei leerer Tabelle
    """
    if not table or not table[0]:
        return ""

    # ── Forward-Fill: None-Zellen mit dem letzten Spaltenwert auffüllen ──────
    # Wir merken uns den letzten nicht-leeren Wert pro Spalte.
    # Das simuliert das Verhalten von Excel bei "verbundenen Zellen".
    num_cols = max(len(row) for row in table)  # Breite der breitesten Zeile
    last_values = [""] * num_cols              # Startwerte: alles leer

    filled_table = []
    for row in table:
        new_row = []
        for col_idx in range(num_cols):
            # Sicher auf Zelle zugreifen (kurze Zeilen mit None auffüllen)
            raw_cell = row[col_idx] if col_idx < len(row) else None
            # Zelle bereinigen: None → "", interne Zeilenumbrüche entfernen
            val = str(raw_cell or "").replace("\n", " ").strip()

            if val:
                # Zelle hat Inhalt → als neuen "letzten Wert" dieser Spalte merken
                last_values[col_idx] = val
            else:
                # Leere Zelle → Forward-Fill: letzten bekannten Wert verwenden
                val = last_values[col_idx]

            new_row.append(val)
        filled_table.append(new_row)

    # ── Markdown-Tabelle zusammenbauen ────────────────────────────────────────
    rows = ["| " + " | ".join(row) + " |" for row in filled_table]

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

    # Trennzeile zwischen Header (erste Zeile) und Datenwzeilen einfügen.
    # Das ist Standard-Markdown-Tabellenformat, das viele LLMs verstehen.
    separator = "| " + " | ".join(["---"] * num_cols) + " |"
    rows.insert(1, separator)
    return "\n".join(rows)


def detect_two_column_layout(page) -> bool:
    """
    Erkennt ob eine PDF-Seite ein zweispaltiges Layout hat.

    WIE FUNKTIONIERT DIE ERKENNUNG?
      Wir schauen, wo die Wörter auf der Seite horizontal verteilt sind.
      Bei zweispaltigen Layouts gibt es eine "leere Mitte" – kaum Wörter
      in einem Bereich von ±20% um die Seitenmitte.

      Wenn sowohl links als auch rechts der Mitte mindestens 30% aller Wörter
      stehen, gilt die Seite als zweispaltig.

    WARUM IST DAS WICHTIG?
      pdfplumber liest Text von oben nach unten, Zeile für Zeile.
      Bei zweispaltigen Layouts mischt er dadurch linke und rechte Spalte
      durcheinander, was den Sinnzusammenhang zerstört.
      Diese Funktion erlaubt es, die Spalten getrennt zu verarbeiten.

    :param page: pdfplumber Page-Objekt
    :returns:    True wenn zweispaltig, False wenn einspaltig oder keine Wörter
    """
    words = page.extract_words()
    if not words or len(words) < 10:
        # Zu wenig Text für eine sinnvolle Erkennung → einspaltig annehmen
        return False

    page_mid = page.width / 2
    # Toleranzbereich um die Mitte (±10% der Seitenbreite)
    margin = page.width * 0.10

    # Wörter zählen die klar links bzw. rechts der Mitte stehen
    left_words  = [w for w in words if w["x1"] < page_mid - margin]
    right_words = [w for w in words if w["x0"] > page_mid + margin]

    total = len(words)
    left_ratio  = len(left_words)  / total
    right_ratio = len(right_words) / total

    # Zweispaltig wenn beide Seiten mindestens 30% der Wörter haben
    return left_ratio >= 0.30 and right_ratio >= 0.30

def _extract_column_content(col_page) -> str:
    """Extrahiert Text und Tabellen aus einem zugeschnittenen Spalten-Bereich."""
    return _extract_regions(col_page)

def _extract_column_content(col_page) -> str:
    """
    Extrahiert Text und Tabellen aus einem bereits zugeschnittenen Spalten-Bereich.

    Diese interne Hilfsfunktion wird von extract_page_content() aufgerufen,
    wenn eine zweispaltige Seite erkannt wurde. Sie verhält sich genau wie
    extract_page_content(), aber arbeitet auf einem bereits per crop()
    ausgeschnittenen Teilbereich der Seite.

    :param col_page: pdfplumber Page-Objekt (bereits per crop() zugeschnitten)
    :returns:        Kombinierter Text+Tabellen-String für diese Spalte
    """
    # Wir rufen die Kern-Extraktionslogik auf dem zugeschnittenen Bereich auf.
    # Da col_page ein vollwertiges pdfplumber-Page-Objekt ist (nur kleiner),
    # funktioniert alles genauso wie bei einer normalen Seite.
    return _extract_regions(col_page)


def _extract_regions(page) -> str:
    """
    Kernlogik der Seitenextraktion: Text und Tabellen in Leserichtung kombinieren.

    Diese Funktion wird intern von extract_page_content() und
    _extract_column_content() verwendet.

    ABLAUF:
      1. Tabellen auf der Seite (oder im Spaltenbereich) finden
      2. Wenn keine Tabellen → einfacher Textextrakt
      3. Seite in horizontale Streifen aufteilen:
           [Text über Tabelle 1] → [Tabelle 1] → [Text zwischen Tabellen] → [Tabelle 2] → ...
      4. Jeden Streifen separat extrahieren und zusammenführen

    WARUM NICHT EINFACH page.extract_text() + page.extract_tables()?
      Der naive Ansatz hängt Tabellen IMMER ans Ende des Seitentexts –
      egal wo sie im PDF stehen. Das zerstört den Kontext:
        "Die Pflichtfächer sind:" → [viel anderer Text] → [ECTS-Tabelle]
      Mit crop() steht die Tabelle genau an der richtigen Stelle.

    :param page: pdfplumber Page-Objekt (oder zugeschnittener Teilbereich)
    :returns:    Kombinierter String mit Text und Markdown-Tabellen in Leserichtung
    """
    # ── Schritt 1: Tabellen finden ────────────────────────────────────────────
    # Zuerst mit Linien-Strategie versuchen (präziser bei Tabellen mit Rahmen)
    table_objects = page.find_tables(table_settings=TABLE_SETTINGS_LINES)

    # Fallback: Wenn keine Tabellen mit Linien gefunden → Text-Strategie versuchen
    # (für linienlose tabellenartige Layouts wie Stundenplan-Gitter)
    if not table_objects:
        table_objects = page.find_tables(table_settings=TABLE_SETTINGS_TEXT)

    # ── Schritt 2: Keine Tabellen → einfache Textextraktion ──────────────────
    if not table_objects:
        return page.extract_text() or ""

    # ── Schritt 3: Tabellen nach Position sortieren (oben → unten) ───────────
    # bbox = (x0, top, x1, bottom) in PDF-Koordinaten (Ursprung oben links)
    sorted_tables = sorted(table_objects, key=lambda t: t.bbox[1])

    regions = []        # Sammlung von ("text" | "table", Inhalt) in Lesereihenfolge
    prev_bottom = 0     # Untere Kante des zuletzt verarbeiteten Bereichs

    for table_obj in sorted_tables:
        x0, top, x1, bottom = table_obj.bbox

        # Koordinaten auf Seitengrenzen begrenzen.
        # Manche PDFs haben fehlerhafte Bounding-Boxes die über den Seitenrand hinausgehen.
        top    = max(top, prev_bottom)
        bottom = min(bottom, page.height)

        # ── Textbereich ÜBER dieser Tabelle extrahieren ───────────────────────
        # crop() schneidet exakt den Bereich zwischen dem letzten verarbeiteten
        # Bereich und dem oberen Rand der aktuellen Tabelle aus.
        if top > prev_bottom:
            text_region = page.crop((0, prev_bottom, page.width, top))
            text = text_region.extract_text()
            if text and text.strip():
                regions.append(("text", text))

        # ── Tabelle extrahieren ───────────────────────────────────────────────
        # .extract() gibt eine Liste von Zeilen zurück (List[List[str|None]])
        table_data = table_obj.extract()
        if table_data:
            regions.append(("table", table_data))

        # Nächsten Textbereich direkt unterhalb dieser Tabelle beginnen
        prev_bottom = bottom

    # ── Textbereich NACH der letzten Tabelle (bis zum Seitenende) ────────────
    if prev_bottom < page.height:
        text_region = page.crop((0, prev_bottom, page.width, page.height))
        text = text_region.extract_text()
        if text and text.strip():
            regions.append(("text", text))

    # ── Alle Regionen zu einem String zusammenführen ─────────────────────────
    parts = []
    for kind, content in regions:
        if kind == "text":
            parts.append(content)
        else:
            # Tabellen-Rohdaten → Markdown-Format (mit Forward-Fill für Merged Cells)
            md = table_to_markdown(content)
            if md:
                parts.append(md)

    # Doppelter Zeilenumbruch als Trennzeichen zwischen Regionen.
    # Das hilft dem Chunking-Algorithmus, saubere Grenzen zu erkennen.
    return "\n\n".join(filter(None, parts))


def extract_page_content(page) -> str:
    """
    Extrahiert den vollständigen Inhalt einer PDF-Seite in korrekter Leserichtung.

    Dies ist die Haupt-Extraktionsfunktion, die für jede Seite aufgerufen wird.
    Sie erkennt automatisch ob die Seite ein- oder zweispaltig ist und wählt
    die passende Strategie.

    VERARBEITUNGSSTRATEGIEN:
      Einspaltig (Normalfall):
        → _extract_regions() direkt auf der ganzen Seite aufrufen

      Zweispaltig (z.B. manche Curriculum-Seiten):
        → Seite in linke und rechte Hälfte teilen (crop())
        → Jede Hälfte separat durch _extract_regions() verarbeiten
        → Ergebnisse zusammenfügen: erst linke Spalte, dann rechte

    :param page: pdfplumber Page-Objekt
    :returns:    Kombinierter String mit Text und Markdown-Tabellen
    """
    # ── Zweispaltige Seiten gesondert behandeln ───────────────────────────────
    if detect_two_column_layout(page):
        page_mid = page.width / 2

        # Linke und rechte Spalte als separate Crop-Bereiche ausschneiden
        left_col  = page.crop((0,        0, page_mid,     page.height))
        right_col = page.crop((page_mid, 0, page.width,   page.height))

        left_text  = _extract_regions(left_col)
        right_text = _extract_regions(right_col)

        # Beide Spalten zusammenführen – linke Spalte zuerst (Lesereihenfolge)
        combined = "\n\n".join(filter(None, [left_text, right_text]))
        return combined

    # ── Einspaltige Seite (Normalfall) ───────────────────────────────────────
    return _extract_regions(page)


def extract_section_heading(text: str) -> Optional[str]:
    """
    Versucht, die erste Abschnittsüberschrift aus dem Rohtext einer Seite zu erkennen.

    ERKANNTE MUSTER:
      1. Paragraphen mit Nummer:  "§ 1 Allgemeines",  "§ 12a Übergangsbestimmungen"
      2. Dezimal-Nummern:         "2.1 Pflichtfächer", "3. Studienaufbau"
      3. VOLLSTÄNDIGE GROSSBUCHSTABEN: "STUDIENPLAN WIRTSCHAFTSINFORMATIK"
         (typisch für Kapitelüberschriften in JKU-Dokumenten)

    WARUM NUR DIE ERSTEN 8 ZEILEN?
      Überschriften stehen bei akademischen Dokumenten fast immer am Seitenanfang.
      Durch die Beschränkung auf 8 Zeilen vermeiden wir False Positives
      (z.B. Abkürzungen in Großbuchstaben mitten im Text).

    :param text: Rohtext einer PDF-Seite (aus page.extract_text())
    :returns:    Erkannte Überschrift als String, oder None wenn keine gefunden
    """
    if not text:
        return None

    for line in text.strip().splitlines()[:8]:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Muster 1+2: Nummerierte Abschnitte (§-Paragraphen oder Dezimalzahlen)
        # Regex-Erklärung: § gefolgt von Zahl, ODER Zahl mit optionalen Unterpunkten
        if re.match(r'^(§\s*\d+[a-z]?|\d+\.(\d+\.)*)\s+\S', line):
            return line

        # Muster 3: Zeile komplett in Großbuchstaben (und keine reine Zahl/Abkürzung)
        if line == line.upper() and len(line) > 3 and not line.isdigit():
            return line

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# DATENBANKOPERATIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def erkennen_abschlussart(pdf_bytes: bytes) -> Optional[str]:
    """
    Erkennt automatisch die Abschlussart eines Studiums aus dem PDF-Inhalt.

    METHODE:
      Die ersten 5 Seiten werden nach Schlüsselwörtern durchsucht.
      Das häufigste Schlüsselwort bestimmt die Abschlussart.
      Bei Gleichstand gewinnt der erste Treffer (Reihenfolge im Dict).

    ERKANNTE ABSCHLUSSARTEN:
      "Bachelor"  → z.B. "Bachelorstudium Wirtschaftsinformatik"
      "Master"    → z.B. "Masterstudium Data Engineering"
      "Diplom"    → z.B. "Diplomstudium Rechtswissenschaften"
      "Lehramt"   → z.B. "Lehramtsstudium"
      "Doktorat"  → z.B. "Doktoratsstudium / PhD"

    :param pdf_bytes: Rohe PDF-Bytes
    :returns:         Abschlussart als String, oder None wenn nicht erkennbar
    """
    import pdfplumber

    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:5]:
            text += (page.extract_text() or "") + "\n"

    text_lower = text.lower()

    # Treffer pro Abschlussart zählen (Regex-Suche nach allen Varianten)
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
    Gibt die UUID eines Studiengangs zurück. Legt ihn an, falls er noch nicht existiert.

    Diese Funktion implementiert das "Upsert"-Muster für Studiengänge:
    Beim ersten Hochladen eines PDFs wird der Studiengang angelegt,
    bei allen weiteren Uploads desselben Studiengangs wird die vorhandene
    UUID zurückgegeben.

    :param code:        Studienkennzahl (z.B. "033 526" für Wirtschaftsinformatik Bachelor)
    :param name:        Vollständiger Studiengangsname
    :param degree_type: Abschlussart (z.B. "Bachelor"), optional
    :returns:           UUID des Studiengangs in der Datenbank
    """
    result = supabase.table("study_programs").select("id").eq("code", code).execute()
    if result.data:
        # Studiengang existiert bereits → UUID zurückgeben
        return result.data[0]["id"]

    row = {"code": code, "name": name}
    if degree_type:
        row["degree_type"] = degree_type

    insert = supabase.table("study_programs").insert(row).execute()
    return insert.data[0]["id"]


def document_exists(filename: str, study_program_id: str) -> bool:
    """
    Prüft ob ein PDF für diesen Studiengang bereits in der Datenbank ist.

    Verhindert doppelte Chunks in der Vektordatenbank, die zu schlechteren
    Suchergebnissen führen würden (doppelte Chunks werden bei der Suche
    mehrfach gefunden und verzerren die Relevanz-Bewertung).

    :param filename:         Dateiname des PDFs (z.B. "curriculum_wi.pdf")
    :param study_program_id: UUID des Studiengangs
    :returns:                True wenn bereits vorhanden, False wenn neu
    """
    result = (
        supabase.table("documents")
        .select("id")
        .eq("filename", filename)
        .eq("study_program_id", study_program_id)
        .execute()
    )
    return len(result.data) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def process_pdf(pdf_bytes: bytes, filename: str, study_program_id: str, user_id: str) -> int:
    """
    Verarbeitet ein Curriculum-PDF vollständig und speichert alle Daten in Supabase.
    NUR für Admin-Nutzung – normale User haben keinen Zugriff auf diese Funktion.

    Dies ist die zentrale Funktion der ETL-Pipeline. Sie orchestriert alle
    Teilschritte und sorgt für eine konsistente Fehlerbehandlung:
    Bei einem Fehler in einem beliebigen Schritt wird der Dokument-Status
    in der Datenbank auf "error" gesetzt, damit der Fehler im Frontend
    angezeigt werden kann.

    VERARBEITUNGSSCHRITTE:
      1.  Duplikat-Check → Abbruch wenn bereits vorhanden
      2.  Studiengang-Code aus DB holen → für den Storage-Pfad
      3.  PDF in Supabase Storage hochladen (Backup des Originals)
      4.  Dokument-Eintrag anlegen (Status: "processing")
      5.  Seitenweise Text + Tabellen extrahieren
          • Inhaltsverzeichnis-Seiten automatisch überspringen
          • Zweispaltige Seiten korrekt verarbeiten
          • Tabellen inline in Leserichtung einbetten
      6.  Texte in Chunks aufteilen (chunking.py)
      7.  Embeddings für alle Chunks generieren (EmbeddingService)
      8.  Chunks mit Metadaten in Supabase speichern
      9.  Dokument-Status auf "processed" setzen

    METADATEN PRO CHUNK:
      - source_filename:  Name der PDF-Datei (für Quellenangabe im Chat)
      - page_number:      Seitenzahl (für Zitat-Anzeige im Frontend)
      - section_heading:  Erkannte Überschrift (für besseres Retrieval)
      - chunk_index:      Fortlaufende Nummer des Chunks im Dokument
      - chunk_type:       "text", "table" oder "mixed" (für gefilterte Suche)
      - has_table:        True/False (für Retrieval-Filter bei Tabellenfragen)

    :param pdf_bytes:        Rohe PDF-Bytes (z.B. von st.file_uploader)
    :param filename:         Originaldateiname, z.B. "curriculum_wi.pdf"
    :param study_program_id: UUID des zugehörigen Studiengangs
    :param user_id:          UUID des hochladenden Users (für RLS-Policy)
    :returns:                Anzahl der erstellten Chunks (für Status-Meldung)
    :raises ValueError:      Wenn das Dokument bereits existiert
    :raises Exception:       Bei Fehlern in der Verarbeitung (Status → "error")
    """
    import pdfplumber

    if document_exists(filename, study_program_id):
        raise ValueError(f"'{filename}' wurde für diesen Studiengang bereits hochgeladen.")

    # ── Schritt 2: Studiengang-Code für Storage-Pfad holen ───────────────────
    # Schrägstriche im Code ersetzen (z.B. "033/526" → "033-526")
    # da Schrägstriche in Storage-Pfaden als Ordner-Trennzeichen gelten.
    program = supabase.table("study_programs").select("code").eq("id", study_program_id).execute()
    program_code = program.data[0]["code"].replace("/", "-") if program.data else "allgemein"
    bucket_path  = f"{program_code}/{filename}"

    # ── Schritt 3: PDF in Supabase Storage hochladen ─────────────────────────
    # "upsert: true" überschreibt eine vorhandene Datei mit gleichem Pfad.
    supabase.storage.from_(BUCKET).upload(
        bucket_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    # ── Schritt 4: Dokument-Eintrag in der DB anlegen ────────────────────────
    # Status "processing" signalisiert dem Frontend, dass die Verarbeitung läuft.
    # Bei Erfolg wird er auf "processed" gesetzt, bei Fehler auf "error".
    doc_result = supabase.table("documents").insert({
        "user_id":          user_id,
        "filename":         filename,
        "bucket_path":      bucket_path,
        "study_program_id": study_program_id,
        "status":           "processing",
    }).execute()
    document_id = doc_result.data[0]["id"]

    try:
        # ── Schritt 5: Seitenweise Text- und Tabellen-Extraktion ─────────────
        # chunks_with_meta: Liste von Dicts mit "content", "page_number",
        #                   "section_heading" und "has_table"
        chunks_with_meta = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):

                # Rohtext separat holen – nur für ToC-Check und Heading-Erkennung.
                # Für den Inhalt nutzen wir extract_page_content() (mit Tabellen inline).
                page_text_raw = page.extract_text() or ""

                # Inhaltsverzeichnis-Seiten überspringen:
                # Viele ". ." Sequenzen (Leitpunkte) = typisches ToC-Muster.
                if page_text_raw.count(". .") > 8:
                    continue

                # Text + Tabellen in der richtigen Leserichtung extrahieren.
                # Diese Funktion erkennt auch zweispaltige Layouts automatisch.
                combined = extract_page_content(page)
                if not combined.strip():
                    continue   # Leere Seiten überspringen (z.B. Deckblatt ohne Text)

                # Überschrift aus dem Rohtext erkennen (für Metadaten-Anreicherung)
                heading = extract_section_heading(page_text_raw)

                # Prüfen ob die Seite Tabellen enthält (für Metadaten-Flag)
                page_has_table = "|" in combined  # Markdown-Tabellen enthalten "|"

                # ── Schritt 6: Chunks für diese Seite erzeugen ───────────────
                for chunk in chunk_text(combined):
                    chunk_has_table = "|" in chunk
                    # Chunk-Typ für spätere Filterung bestimmen:
                    # "table"  → Chunk enthält nur/hauptsächlich Tabelle
                    # "mixed"  → Chunk hat Text + Tabelle
                    # "text"   → Chunk hat nur Text
                    if chunk_has_table:
                        chunk_type = "table" if chunk.strip().startswith("|") else "mixed"
                    else:
                        chunk_type = "text"

                    chunks_with_meta.append({
                        "content":         chunk,
                        "page_number":     page_num,
                        "section_heading": heading,        # None wenn nicht erkannt
                        "has_table":       chunk_has_table,
                        "chunk_type":      chunk_type,
                    })

        # ── Schritt 7: Embeddings für alle Chunks auf einmal generieren ───────
        # Batch-Verarbeitung ist deutlich effizienter als einzelne API-Aufrufe.
        # Das E5-Modell erzeugt 768-dimensionale Vektoren pro Chunk.
        embed_service = EmbeddingService()
        embeddings    = embed_service.embed_texts([c["content"] for c in chunks_with_meta])

        # ── Schritt 8: Chunks + Metadaten in Supabase speichern ──────────────
        for i, (chunk_meta, vector) in enumerate(zip(chunks_with_meta, embeddings)):
            supabase.table("chunks").insert({
                "document_id": document_id,
                "content":     chunk_meta["content"],
                "embedding":   vector,          # 768-dimensionaler Zahlenvektor
                "chunk_index": i,
                "metadata": {
                    # Alle Metadaten werden als JSON gespeichert.
                    # Sie können beim Retrieval für Filter genutzt werden,
                    # z.B. "such nur in Chunks die Tabellen enthalten".
                    "source_filename":  filename,
                    "page_number":      chunk_meta["page_number"],
                    "section_heading":  chunk_meta["section_heading"],
                    "chunk_index":      i,
                    "has_table":        chunk_meta["has_table"],
                    "chunk_type":       chunk_meta["chunk_type"],
                },
            }).execute()

        # ── Schritt 9: Dokument als erfolgreich verarbeitet markieren ─────────
        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()

    except Exception as e:
        # Bei jedem Fehler: Status auf "error" setzen, dann Exception weiterwerfen.
        # Das Frontend kann dann eine Fehlermeldung anzeigen und der Admin
        # kann das Dokument erneut hochladen.
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        raise e

    return len(chunks_with_meta)


# ═══════════════════════════════════════════════════════════════════════════════
# USER-PIPELINE: ICS-Kalender
# ═══════════════════════════════════════════════════════════════════════════════

def process_ics(ics_bytes: bytes, filename: str, user_id: str) -> int:
    """
    Verarbeitet eine KUSSS-ICS-Datei und speichert Events in der `events`-Tabelle.

    ICS (iCalendar) ist das Standardformat für Kalender-Exports, z.B. von
    KUSSS (JKU Stundenplan-Export). Diese Funktion ermöglicht es, auch
    Veranstaltungsdaten in den Assistenten einzuspeisen.

    ABLAUF:
      ICS-Bytes → temporäre Datei auf Disk → ingest_ics.parse_ics() →
      Events als strukturierte Dicts → Supabase "events"-Tabelle

    WARUM TEMPORÄRE DATEI?
      Die ingest_ics-Bibliothek erwartet einen Dateipfad, kein Bytes-Objekt.
      Die temporäre Datei wird nach der Verarbeitung automatisch gelöscht.

    :param ics_bytes: Rohe ICS-Bytes (aus Datei-Upload)
    :param filename:  Originaldateiname (für Logging/Debugging)
    :param user_id:   UUID des hochladenden Users
    :returns:         Anzahl der importierten Kalender-Events
    """
    import tempfile
    from ingest_ics import parse_ics

    # Temporäre Datei erstellen und ICS-Bytes hineinschreiben
    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        tmp.write(ics_bytes)
        tmp_path = tmp.name

    try:
        events = parse_ics(tmp_path)

        for event in events:
            supabase.table("events").insert({
                "user_id":   user_id,
                "title":     event.get("title"),
                "start":     event.get("start"),
                "end":       event.get("end"),
                "location":  event.get("location"),
                "source":    filename,
            }).execute()

    finally:
        # Temporäre Datei immer löschen (auch bei Fehlern)
        os.unlink(tmp_path)

    return len(events)
