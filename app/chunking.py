"""
chunking.py – Text-Bereinigung und semantisches Chunking für die RAG-Pipeline.

Ablauf:
  Rohtext (inkl. Markdown-Tabellen von extract_page_content)
    → clean_text()   : Artefakte entfernen, Zeilen zusammenführen, Tabellenstruktur schützen
    → chunk_text()   : Sinnvolle Abschnitte bilden mit drei Strategien:
        1. Tabellenblöcke werden als atomare Einheit behandelt (nie mitten zerrissen)
        2. Tabellenblöcke bekommen den letzten Satz des vorherigen Chunks als
           "Lead-in" mitgegeben → LLM versteht den Kontext der Tabelle
        3. Normaler Text wird an Satzgrenzen mit Overlap-Technik aufgeteilt
    → Liste von Strings, bereit für Embedding-Generierung
"""

import re
from typing import List


def clean_text(text: str) -> str:
    """
    Bereinigt Rohtext aus PDFs.

    Schritte:
      A. PDF-spezifische Footer-Zeilen entfernen (z.B. "Seite 2 von 16")
      B. Silbentrennung rückgängig machen ("Lehrveranstal-\\ntung" → "Lehrveranstaltung")
      C. Zusammengeklebte Wörter trennen ("Basisund" → "Basis und")
      D. Harte Zeilenumbrüche zusammenführen – Markdown-Tabellenzeilen bleiben intakt
      E. Mehrfache Leerzeichen entfernen

    :param text: Rohtext aus pdfplumber
    :returns:    Bereinigter Text
    """
    if not text:
        return ""

    # A. PDF-Footer entfernen (Genehmigungsvermerke, Seitenzahlen)
    text = re.sub(r'GenehmigtvomSenat\S+.*?Inkrafttreten:\S+', '', text)
    text = re.sub(r'Seite\s*\d+\s*von\s*\d+', '', text)

    # B. Silbentrennung reparieren: "Wort-\nfort" → "Wortfort"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # C. Zusammengeklebte Wörter trennen (passiert oft bei pdfplumber-Extraktion):
    #    Erkennt: Kleinbuchstabe direkt gefolgt von Großbuchstabe → Leerzeichen einfügen
    text = re.sub(r'([a-zäöüß])([A-ZÄÖÜ])', r'\1 \2', text)

    # D. Zeilen zusammenführen – unterscheidet zwischen:
    #    - Tabellenzeilen (beginnen mit "|"): Zeilenumbruch beibehalten → Tabellenstruktur bleibt
    #    - Zeilen ohne Satzzeichen am Ende: Leerzeichen anhängen (gehören zusammen)
    #    - Zeilen mit Satzzeichen am Ende: echten Absatz-Umbruch einfügen
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue    # Leerzeilen überspringen
        cleaned_lines.append(line)
        if line.startswith('|'):
            # Markdown-Tabellenzeile → Zeilenumbruch beibehalten
            cleaned_lines[-1] += "\n"
        elif not re.search(r'[.!?:]$', line):
            # Zeile endet nicht mit Satzzeichen → nächste Zeile gehört wahrscheinlich dazu
            cleaned_lines[-1] += " "
        else:
            # Satzende erkannt → echter Absatzumbruch
            cleaned_lines[-1] += "\n"

    text = "".join(cleaned_lines)

    # E. Mehrfache Leerzeichen auf eines reduzieren (Zeilenumbrüche \n bleiben erhalten)
    text = re.sub(r"[^\S\n]+", " ", text)

    return text.strip()


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 150) -> List[str]:
    """
    Teilt bereinigten Text in semantisch sinnvolle Chunks auf.

    Strategie:
      1. Text in Segmente aufteilen: Markdown-Tabellenblöcke vs. normaler Text
      2. Tabellenblöcke bleiben als Ganzes erhalten (oder bekommen einen eigenen Chunk)
      3. Normaler Text wird an Satzgrenzen geschnitten
      4. Overlap: Der letzte Satz des vorherigen Chunks wird an den Anfang
         des nächsten kopiert → Kontext bleibt über Chunk-Grenzen hinweg erhalten

    :param text:       Rohtext (bereits bereinigt oder wird intern bereinigt)
    :param chunk_size: Max. Zeichenanzahl pro Chunk (Standard: 600)
    :param overlap:    Zeichenanzahl für harte Schnitte bei Überlänge/Overlap (Standard: 150)
    :returns:          Liste von Chunk-Strings, bereit für Embedding-Generierung
    """
    # Zuerst bereinigen
    text = clean_text(text)

    # ── Schritt 1: Text in Tabellen- und Text-Segmente aufteilen ─────────────
    # Ein Tabellenblock = eine oder mehrere aufeinanderfolgende Zeilen die mit | beginnen
    table_re = re.compile(r'((?:\|[^\n]*\n)+)', re.MULTILINE)
    segments: list[tuple[bool, str]] = []  # (is_table, content)
    last_end = 0
    for m in table_re.finditer(text):
        if m.start() > last_end:
            segments.append((False, text[last_end:m.start()]))  # Text vor der Tabelle
        segments.append((True, m.group().strip()))               # Tabellenblock
        last_end = m.end()
    if last_end < len(text):
        segments.append((False, text[last_end:]))                # Text nach letzter Tabelle

    chunks: List[str] = []
    current_chunk = ""  # Aktuell aufgebauter Chunk (noch nicht gespeichert)

    def flush() -> None:
        """Aktuellen Chunk speichern und zurücksetzen."""
        nonlocal current_chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        current_chunk = ""

    # ── Schritt 2 & 3: Segmente verarbeiten ──────────────────────────────────
    for is_table, segment in segments:

        if is_table:
            # ── Tabellenblock-Strategie ───────────────────────────────────────
            # Tabellen werden NIE mitten zerrissen – sie bleiben immer als Einheit.

            if current_chunk and len(current_chunk) + len(segment) + 2 <= chunk_size:
                # Tabelle passt noch in den laufenden Chunk → direkt anhängen
                current_chunk += "\n\n" + segment + "\n\n"
            else:
                # Tabelle passt nicht mehr → neuen Chunk starten.
                # Lead-in: Letzten Satz des aktuellen Chunks als Kontextsatz
                # mitgeben, damit der LLM weiß, worüber die Tabelle handelt
                # (z.B. "Die Pflichtfächer umfassen folgende Kurse:" bleibt
                #  im selben Chunk wie die ECTS-Tabelle darunter).
                lead_in = ""
                if current_chunk.strip():
                    prev_sentences = re.split(r'(?<=[.!?]) +', current_chunk.strip())
                    lead_in = prev_sentences[-1].strip() if prev_sentences else ""

                flush()

                if lead_in:
                    # Lead-in + Tabelle zusammen speichern (kann chunk_size überschreiten –
                    # das ist gewollt, da Tabellen nicht zerrissen werden sollen)
                    chunks.append(f"{lead_in}\n\n{segment}")
                else:
                    # Kein vorheriger Text → Tabelle direkt als eigenen Chunk
                    chunks.append(segment)

        else:
            # Normaler Text: an Satzenden aufteilen
            sentences = re.split(r'(?<=[.!?]) +', segment)

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                if len(sentence) > chunk_size:
                    # Einzelner Satz ist zu lang → hart an Wortgrenzen schneiden
                    flush()
                    for i in range(0, len(sentence), chunk_size - overlap):
                        end = min(i + chunk_size, len(sentence))
                        if end < len(sentence):
                            # Auf nächste Wortgrenze runden (kein Schnitt mitten im Wort)
                            space_pos = sentence.rfind(' ', i, end)
                            if space_pos > i:
                                end = space_pos
                        chunks.append(sentence[i:end].strip())
                    continue

                if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                    # Satz passt noch in den aktuellen Chunk
                    current_chunk += sentence + " "
                else:
                    # ── Schritt 4: Overlap ────────────────────────────────────
                    # Letzten Satz des aktuellen Chunks als Kontext-Überlapp mitnehmen
                    prev_sentences = re.split(r'(?<=[.!?]) +', current_chunk.strip())
                    overlap_text = (prev_sentences[-1] + " ") if prev_sentences else ""
                    flush()
                    # Neuen Chunk mit Overlap-Text + aktuellem Satz starten
                    if len(overlap_text) + len(sentence) <= chunk_size:
                        current_chunk = overlap_text + sentence + " "
                    else:
                        current_chunk = sentence + " "

    # Letzten offenen Chunk speichern
    flush()

    # Leere Strings herausfiltern (können durch Regex-Splits entstehen)
    return [c for c in chunks if c.strip()]
