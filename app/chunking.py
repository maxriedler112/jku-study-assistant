"""
chunking.py – Text-Bereinigung und semantisches Chunking für die RAG-Pipeline.
===============================================================================

Diese Datei ist für die "Portionierung" des extrahierten Textes zuständig.
Das KI-Modell kann nicht ganze PDFs auf einmal verarbeiten – es braucht
kleine, thematisch zusammenhängende Abschnitte ("Chunks").

ABLAUF:
  Rohtext (inkl. Markdown-Tabellen von extract_page_content aus pipeline.py)
    │
    ▼
  clean_text()
    Artefakte entfernen, Silbentrennung reparieren, Zeilen zusammenführen,
    Tabellenstruktur (Markdown "|"-Zeilen) schützen
    │
    ▼
  chunk_text()
    Text in sinnvolle Abschnitte aufteilen – mit drei Strategien:
      1. Tabellenblöcke werden als atomare Einheit behandelt (nie zerrissen)
      2. Tabellenblöcke erhalten den Überschrifts-Kontext + den letzten Satz
         des vorherigen Chunks als "Lead-in" → LLM versteht den Tabellenkontext
      3. Normaler Text wird an Satzgrenzen mit Overlap-Technik aufgeteilt
         → Kontext bleibt über Chunk-Grenzen hinweg erhalten
    │
    ▼
  Liste von Strings → bereit für Embedding-Generierung (embeddings.py)

WARUM CHUNKS STATT VOLLTEXTSUCHE?
  Embeddings funktionieren am besten bei kurzen, thematisch fokussierten Texten.
  Zu lange Chunks "verwässern" den Vektor (viele Themen → kein klarer Schwerpunkt).
  Zu kurze Chunks verlieren den Kontext.
  600 Zeichen mit 150 Zeichen Overlap ist ein bewährter Kompromiss für
  akademische Dokumente wie Curricula.

Abhängigkeiten: Nur Python-Standardbibliothek (re, typing)
"""

import re
from typing import List


def clean_text(text: str) -> str:
    """
    Bereinigt Rohtext aus PDFs und bereitet ihn für das Chunking vor.

    PDFs sind oft "schmutziger" als sie aussehen: Silbentrennung über
    Zeilenenden, zusammengeklebte Wörter durch Encoding-Fehler, Footer-Texte
    die mitten in Absätzen auftauchen, etc. Diese Funktion behebt diese
    häufigen Probleme systematisch.

    VERARBEITUNGSSCHRITTE:
      A. PDF-Footer entfernen
         Muster wie "Seite 3 von 16" oder automatisch eingefügte
         Genehmigungsvermerke werden gelöscht.

      B. Silbentrennung reparieren
         PDFs trennen lange Wörter am Zeilenende mit Bindestrich:
         "Lehrveranstal-\ntung" → "Lehrveranstaltung"
         Das ist wichtig damit das Embedding das Wort korrekt erkennt.

      C. Zusammengeklebte Wörter trennen
         pdfplumber verbindet manchmal Wörter ohne Leerzeichen:
         "Basisund" → "Basis und", "WirtschaftsinformatikerInnen" bleibt
         Erkennungsmuster: Kleinbuchstabe direkt gefolgt von Großbuchstabe

      D. Zeilenumbrüche intelligent zusammenführen
         Drei Fälle werden unterschieden:
         - Tabellenzeilen (beginnen mit "|"): Zeilenumbruch beibehalten!
           → Markdown-Tabellenstruktur darf nicht zerstört werden
         - Zeile endet ohne Satzzeichen: Leerzeichen anhängen
           → Nächste Zeile gehört zum selben Satz
         - Zeile endet mit Satzzeichen: echter Absatzumbruch
           → Klarer Trennpunkt für den Chunking-Algorithmus

      E. Mehrfache Leerzeichen normalisieren
         Doppelte/dreifache Leerzeichen auf eines reduzieren.
         Zeilenumbrüche (\\n) bleiben dabei erhalten!

    :param text: Rohtext aus pdfplumber (oder kombinierter Text aus extract_page_content)
    :returns:    Bereinigter Text, bereit für chunk_text()
    """
    if not text:
        return ""

    # ── A. PDF-Footer entfernen ───────────────────────────────────────────────
    # Genehmigungsvermerke wie "GenehmigtvomSenat2024-05-12Inkrafttreten:2024-10-01"
    # entstehen wenn pdfplumber die Fußzeile ohne Leerzeichen zusammensetzt.
    text = re.sub(r'GenehmigtvomSenat\S+.*?Inkrafttreten:\S+', '', text)
    # Seitenzahlen-Muster: "Seite 3 von 16", "Seite3von16", etc.
    text = re.sub(r'Seite\s*\d+\s*von\s*\d+', '', text)

    # ── B. Silbentrennung reparieren ─────────────────────────────────────────
    # Regex: Buchstabe + Bindestrich + optionales Leerzeichen + Zeilenumbruch + Buchstabe
    # → Bindestrich und Umbruch entfernen, Wörter zusammenfügen
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # ── C. Zusammengeklebte Wörter trennen ───────────────────────────────────
    # Erkennt: Kleinbuchstabe (inkl. deutsche Umlaute) direkt vor Großbuchstabe
    # ACHTUNG: Echte CamelCase-Wörter wie "iPhone" werden auch getrennt → akzeptabler
    # Trade-off für akademische Texte die kein CamelCase verwenden
    text = re.sub(r'([a-zäöüß])([A-ZÄÖÜ])', r'\1 \2', text)

    # ── D. Zeilenumbrüche intelligent zusammenführen ─────────────────────────
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue    # Komplett leere Zeilen überspringen

        cleaned_lines.append(line)

        if line.startswith('|'):
            # TABELLENZEILE: Zeilenumbruch beibehalten!
            # Markdown-Tabellen brauchen echte Zeilenumbrüche zwischen den Zeilen.
            # Würden wir sie zusammenführen, wäre die Tabelle kaputt.
            cleaned_lines[-1] += "\n"

        elif not re.search(r'[.!?:]$', line):
            # KEIN SATZZEICHEN AM ENDE: Nächste Zeile gehört dazu
            # → Leerzeichen anhängen statt Zeilenumbruch
            # Beispiel: "Die Pflichtfächer des ersten" + " Semesters umfassen..."
            cleaned_lines[-1] += " "

        else:
            # SATZZEICHEN AM ENDE: Echter Absatzumbruch
            # → \n einfügen damit chunk_text() später saubere Grenzen findet
            cleaned_lines[-1] += "\n"

    text = "".join(cleaned_lines)

    # ── E. Mehrfache Leerzeichen normalisieren ────────────────────────────────
    # [^\S\n] = alles was Whitespace ist, aber kein Zeilenumbruch
    # → Mehrfache Leerzeichen/Tabs auf eines reduzieren, \n bleibt erhalten
    text = re.sub(r"[^\S\n]+", " ", text)

    return text.strip()


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 150) -> List[str]:
    """
    Teilt bereinigten Text in semantisch sinnvolle Chunks auf und bettet in
    jeden Chunk den zugehörigen Sektions-Header ein (Contextual Chunking).

    WARUM CONTEXTUAL CHUNKING?
      Ohne Header-Einbettung kann ein Chunk wie "Die LVA wird auf Deutsch
      gehalten. 3 ECTS." nicht dem richtigen Fach zugeordnet werden – der
      Embedding-Vektor enthält keine Information darüber, zu welchem Paragraph
      dieser Text gehört. Durch das Voranstellen des Headers (z.B.
      "[§ 5 Einführung in Wirtschaftsinformatik]") enthält jeder Chunk diese
      Information explizit, sodass die Vektorsuche ihn auch bei Fragen wie
      "Was lerne ich in Einführung in WI?" korrekt findet.

    DREI-STRATEGIE-ANSATZ:

    Strategie 1 – Tabellenblöcke (atomare Einheit):
      Tabellen werden NIEMALS zerrissen. Eine halbierte ECTS-Tabelle ist
      für das LLM wertlos ("Hat Mathematik 4 oder 5 ECTS? → Zeile fehlt!").
      Wenn eine Tabelle zu groß für einen Chunk ist, bekommt sie einen
      eigenen Chunk – auch wenn dieser chunk_size überschreitet.

    Strategie 2 – Lead-in + Header für Tabellen (Kontext-Erhalt):
      Tabellen werden oft eingeleitet: "Die Pflichtfächer des 2. Semesters sind:"
      Ohne diesen Einleitungssatz weiß das LLM nicht, was die Tabelle zeigt.
      Lösung: Den letzten Satz des vorherigen Chunks ALS ERSTES in den
      Tabellen-Chunk einfügen ("Lead-in"). Zusätzlich wird der aktuelle
      Sektions-Header ganz vorne eingefügt, sodass auch Tabellen-Chunks
      eindeutig einem Fach/Paragraphen zugeordnet werden können.

    Strategie 3 – Overlap + Header für Fließtext (Kontext-Kontinuität):
      Wenn ein Chunk voll ist und ein neuer beginnt, wird der letzte Satz
      des alten Chunks an den Anfang des neuen kopiert (Overlap). Beim
      Abschließen (flush) wird dem gespeicherten Chunk außerdem der aktuell
      gültige Sektions-Header vorangestellt – sofern er nicht bereits im
      Chunk-Text enthalten ist. So trägt jeder Fließtext-Chunk den Kontext
      seines Paragraphen, egal wie weit er vom Header-Satz entfernt liegt.

    HEADING-WECHSEL-LOGIK:
      Sobald eine neue Überschrift erkannt wird (§-Paragraph oder Dezimalnummer),
      wird der bisherige Chunk sofort mit dem ALTEN Header abgeschlossen (flush),
      bevor current_heading überschrieben wird. Dadurch landet kein Chunk
      in der falschen Sektion und es gibt keine "Mischchunks" über Sektionsgrenzen.

    PARAMETER:
      chunk_size: 600 Zeichen ≈ 90–100 Wörter ≈ optimal für multilingual-e5-base.
                  Größere Werte verwässern den Embedding-Vektor (zu viele Themen).
                  Kleinere Werte verlieren den Kontext.
      overlap:    150 Zeichen ≈ 1–2 Sätze als Kontext-Brücke beim harten Schnitt
                  langer Einzelsätze.

    :param text:       Rohtext aus extract_page_content() / pipeline.py.
                       Wird intern durch clean_text() bereinigt (idempotent).
    :param chunk_size: Maximale Zeichenanzahl pro Chunk (Standard: 600).
    :param overlap:    Zeichenanzahl Überlapp beim Zerteilen langer Einzelsätze
                       (Standard: 150).
    :returns:          Liste von Chunk-Strings im Format:
                         "[§ N Sektionsname]\n<Inhalt>"
                       bereit für EmbeddingService.embed_texts().
    """
    # Zuerst bereinigen (clean_text() ist idempotent – doppelter Aufruf schadet nicht)
    text = clean_text(text)

    if not text.strip():
        return []

    # ── Schritt 1: Text in Tabellen- und Fließtext-Segmente aufteilen ─────────
    # Regex erkennt Blöcke von aufeinanderfolgenden Markdown-Tabellenzeilen.
    # Eine Tabellenzeile beginnt immer mit "|" und endet mit "\n".
    # Beispiel: "| Fach | ECTS |\n| --- | --- |\n| Mathematik | 4 |\n"
    table_re = re.compile(r'((?:\|[^\n]*\n)+)', re.MULTILINE)

    # segments: Liste von (is_table: bool, content: str)
    # is_table=True  → Markdown-Tabellenblock
    # is_table=False → normaler Fließtext
    segments: list[tuple[bool, str]] = []
    last_end = 0

    for m in table_re.finditer(text):
        if m.start() > last_end:
            segments.append((False, text[last_end:m.start()]))
        segments.append((True, m.group().strip()))
        last_end = m.end()

    if last_end < len(text):
        segments.append((False, text[last_end:]))

    chunks: List[str] = []
    current_chunk = ""   # Aktuell aufgebauter, noch nicht gespeicherter Chunk
    current_heading = "" # Zuletzt erkannte Kapitelüberschrift

    def flush() -> None:
        """
        Schließt den aktuellen Chunk ab, stellt den Sektions-Header voran
        und speichert ihn in der chunks-Liste.

        Der Header wird nur vorangestellt, wenn er nicht bereits am Anfang
        des Chunk-Textes steht – das verhindert doppelte Header bei Chunks,
        die direkt mit dem Überschrifts-Satz beginnen.
        Anschließend wird current_chunk zurückgesetzt.
        """
        nonlocal current_chunk
        if current_chunk.strip():
            content = current_chunk.strip()
            # Sektions-Header voranstellen, sofern noch nicht enthalten
            if current_heading and not content.startswith(current_heading):
                content = f"[{current_heading}]\n{content}"
            chunks.append(content)
        current_chunk = ""

    def get_last_sentence(text_block: str) -> str:
        """
        Extrahiert den letzten vollständigen Satz aus einem Textblock.

        Wird als "Lead-in" vor Tabellenblöcken verwendet: Der letzte Satz
        des vorherigen Chunks erklärt typischerweise, worum es in der
        folgenden Tabelle geht (z.B. "Die Pflichtfächer des 2. Semesters sind:").

        :param text_block: Beliebiger Textblock.
        :returns:          Letzter Satz ohne abschließende Leerzeichen.
        """
        sentences = re.split(r'(?<=[.!?]) +', text_block.strip())
        return sentences[-1].strip() if sentences else ""

    # ── Schritt 2 & 3: Segmente der Reihe nach verarbeiten ───────────────────
    for is_table, segment in segments:

        if is_table:
            # ════════════════════════════════════════════════════════════════
            # STRATEGIE 1 & 2: Tabellenblock-Verarbeitung
            # ════════════════════════════════════════════════════════════════

            # Tabelle passt noch in den laufenden Chunk → einfach anhängen
            if current_chunk and len(current_chunk) + len(segment) + 2 <= chunk_size:
                current_chunk += "\n\n" + segment + "\n\n"
            else:
                # Tabelle passt nicht mehr → neuen Chunk starten.
                # Lead-in: Letzten Satz des aktuellen Chunks extrahieren,
                # damit der Tabellen-Chunk seinen thematischen Kontext kennt.
                lead_in = get_last_sentence(current_chunk) if current_chunk.strip() else ""

                # Aktuellen Chunk mit dem bisherigen Header abschließen
                flush()

                # Tabellen-Chunk zusammenbauen:
                # [Header (optional)] + [Lead-in-Satz (optional)] + [Tabelle]
                table_parts = []
                if current_heading:
                    table_parts.append(f"[{current_heading}]")
                if lead_in:
                    table_parts.append(lead_in)
                table_parts.append(segment)

                # WICHTIG: chunk_size wird für Tabellen bewusst NICHT erzwungen!
                # Eine halbierte Tabelle ist wertloser als ein zu großer Chunk.
                chunks.append("\n\n".join(table_parts))

        else:
            # ════════════════════════════════════════════════════════════════
            # STRATEGIE 3: Fließtext-Verarbeitung mit Overlap + Header
            # ════════════════════════════════════════════════════════════════

            # Kapitelüberschrift aus dem Segment erkennen (erste 8 Zeilen).
            # Erkannte Muster:
            #   § 5 Einführung in Wirtschaftsinformatik  → §-Paragraph
            #   2.1 Pflichtfächer                        → Dezimalnummer
            #   STUDIENPLAN WIRTSCHAFTSINFORMATIK        → Vollständige Großbuchstaben
            for line in segment.splitlines()[:8]:
                line = line.strip()
                if not line:
                    continue
                if (line == line.upper() and len(line) > 5 and not line.isdigit()) or \
                   re.match(r'^(§\s*\d+[a-z]?|\d+\.(\d+\.)*)\s+\S', line):
                    # Heading-Wechsel: alten Chunk mit altem Header abschließen,
                    # BEVOR current_heading überschrieben wird. So landet kein
                    # Chunk irrtümlich unter dem falschen Paragraphen.
                    if line != current_heading:
                        flush()
                        current_heading = line
                    break

            # Text an Satzgrenzen aufteilen.
            # (?<=[.!?]) ist ein "Lookbehind": splittet NACH dem Satzzeichen,
            # lässt das Satzzeichen aber beim vorherigen Element.
            sentences = re.split(r'(?<=[.!?]) +', segment)

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                # Einzelner Satz länger als chunk_size (seltener Grenzfall):
                # Hart an Wortgrenzen zerschneiden. Jedes Teilstück bekommt
                # den aktuellen Header vorangestellt.
                if len(sentence) > chunk_size:
                    flush()
                    i = 0
                    while i < len(sentence):
                        end = min(i + chunk_size, len(sentence))
                        if end < len(sentence):
                            space_pos = sentence.rfind(' ', i, end)
                            if space_pos > i:
                                end = space_pos
                        part = sentence[i:end].strip()
                        if current_heading:
                            part = f"[{current_heading}]\n{part}"
                        chunks.append(part)
                        i = end
                    continue

                if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                    # Satz passt in den aktuellen Chunk → anhängen
                    current_chunk += sentence + " "
                else:
                    # Chunk ist voll → OVERLAP-MECHANISMUS:
                    # Letzten Satz des aktuellen Chunks als Kontext-Brücke
                    # an den Anfang des nächsten Chunks stellen.
                    overlap_text = get_last_sentence(current_chunk) + " "
                    flush()
                    if len(overlap_text) + len(sentence) <= chunk_size:
                        current_chunk = overlap_text + sentence + " "
                    else:
                        # Overlap alleine schon zu groß → direkt mit neuem Satz beginnen
                        current_chunk = sentence + " "

    # Letzten offenen Chunk nicht vergessen!
    flush()

    # Sicherheits-Filter: Leere Strings entfernen
    return [c for c in chunks if c.strip()]

    def flush() -> None:
        """
        Speichert den aktuellen Chunk in die chunks-Liste und setzt ihn zurück.

        Diese innere Hilfsfunktion vermeidet Code-Duplizierung: Ohne sie müssten
        wir an jedem Punkt wo ein Chunk abgeschlossen wird dieselben 3 Zeilen
        wiederholen. Als nonlocal-Funktion kann sie direkt auf current_chunk
        und chunks aus dem äußeren Scope zugreifen.
        """
        nonlocal current_chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        current_chunk = ""

    def get_last_sentence(text_block: str) -> str:
        """
        Extrahiert den letzten vollständigen Satz aus einem Textblock.

        Wird für den Lead-in vor Tabellenblöcken verwendet: Der letzte Satz
        des vorherigen Chunks erklärt oft, worum es in der folgenden Tabelle geht.

        Beispiel: "Die Lehrveranstaltungen des 3. Semesters sind:" → Lead-in
                  | LV-Name | ECTS | Typ |    → Tabelle
                  | Algorithmen | 4 | VL |

        :param text_block: Beliebiger Textblock
        :returns:          Letzter Satz (ohne abschließende Leerzeichen)
        """
        sentences = re.split(r'(?<=[.!?]) +', text_block.strip())
        return sentences[-1].strip() if sentences else ""

    # ── Schritt 2 & 3: Segmente der Reihe nach verarbeiten ───────────────────
    for is_table, segment in segments:

        if is_table:
            # ════════════════════════════════════════════════════════════════
            # STRATEGIE 1 & 2: Tabellenblock-Verarbeitung
            # ════════════════════════════════════════════════════════════════

            # Tabelle passt noch in den laufenden Chunk → einfach anhängen
            if current_chunk and len(current_chunk) + len(segment) + 2 <= chunk_size:
                current_chunk += "\n\n" + segment + "\n\n"

            else:
                # Tabelle passt nicht mehr → neuen Chunk starten.

                # Lead-in: Letzten Satz des aktuellen Chunks extrahieren.
                # Dieser Satz erklärt typischerweise, was die Tabelle zeigt.
                lead_in_sentence = get_last_sentence(current_chunk) if current_chunk.strip() else ""

                # Aktuellen Chunk abschließen
                flush()

                # Tabellen-Chunk zusammenbauen:
                # [Überschrift (optional)] + [Lead-in-Satz (optional)] + [Tabelle]
                table_parts = []

                if current_heading:
                    # Überschrift ganz vorne → LLM weiß sofort in welchem Kontext
                    # die Tabelle steht, auch wenn der Lead-in-Satz fehlt
                    table_parts.append(f"Abschnitt: {current_heading}")

                if lead_in_sentence:
                    table_parts.append(lead_in_sentence)

                table_parts.append(segment)

                # Tabellen-Chunk speichern.
                # WICHTIG: chunk_size wird hier bewusst NICHT erzwungen!
                # Eine halbierte Tabelle ist wertloser als ein zu großer Chunk.
                chunks.append("\n\n".join(table_parts))

        else:
            # ════════════════════════════════════════════════════════════════
            # STRATEGIE 3: Fließtext-Verarbeitung mit Overlap
            # ════════════════════════════════════════════════════════════════

            # Kapitelüberschriften aus dem Text erkennen und merken.
            # Heuristik: Zeile komplett in Großbuchstaben ODER nummerierter Abschnitt
            for line in segment.splitlines()[:5]:
                line = line.strip()
                if not line:
                    continue
                if (line == line.upper() and len(line) > 5 and not line.isdigit()) or \
                   re.match(r'^(§\s*\d+|\d+\.(\d+\.)*)\s+\S', line):
                    current_heading = line
                    break

            # Text an Satzgrenzen aufteilen.
            # (?<=[.!?]) ist ein "Lookbehind": splittet NACH dem Satzzeichen,
            # aber lässt das Satzzeichen beim vorherigen Element.
            sentences = re.split(r'(?<=[.!?]) +', segment)

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                # Einzelner Satz ist länger als chunk_size (seltener Grenzfall):
                # Hart an Wortgrenzen zerschneiden mit Overlap-Versatz
                if len(sentence) > chunk_size:
                    flush()  # Bisherigen Chunk abschließen
                    i = 0
                    while i < len(sentence):
                        end = min(i + chunk_size, len(sentence))
                        if end < len(sentence):
                            # Auf nächste Wortgrenze runden (kein Schnitt mitten im Wort)
                            space_pos = sentence.rfind(' ', i, end)
                            if space_pos > i:
                                end = space_pos
                        chunks.append(sentence[i:end].strip())
                        i = end
                    continue

                if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                    # ── Satz passt in den aktuellen Chunk ────────────────────
                    current_chunk += sentence + " "

                else:
                    # ── Chunk ist voll → OVERLAP-MECHANISMUS ─────────────────
                    # Letzten Satz des aktuellen Chunks als Kontext-Brücke
                    # an den Anfang des nächsten Chunks stellen.
                    # So bleibt der Kontext über die Chunk-Grenze hinweg erhalten.
                    overlap_text = get_last_sentence(current_chunk) + " "

                    flush()  # Alten Chunk abschließen

                    # Neuen Chunk mit Overlap-Text beginnen
                    if len(overlap_text) + len(sentence) <= chunk_size:
                        # Overlap + neuer Satz passen zusammen → ideal
                        current_chunk = overlap_text + sentence + " "
                    else:
                        # Overlap-Text alleine schon zu groß (sehr langer Satz) →
                        # direkt mit dem neuen Satz beginnen (kein Overlap)
                        current_chunk = sentence + " "

    # Letzten offenen Chunk nicht vergessen!
    flush()

    # Sicherheits-Filter: Leere Strings entfernen (können durch Regex-Splits entstehen)
    return [c for c in chunks if c.strip()]