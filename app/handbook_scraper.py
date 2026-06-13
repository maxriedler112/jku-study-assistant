"""
handbook_scraper.py – Zweistufiger Admin-Scraper für das JKU Studienhandbuch.
==============================================================================

SCRAPING-STRATEGIE (zweistufig):
---------------------------------
Stufe 1 – Übersichtsseite (z.B. /curr/1193):
    • Enthält die hierarchische Modulstruktur des Studiengangs
      (Module → Gruppen → Lehrveranstaltungen)
    • Extrahiert strukturierte Overview-Chunks inklusive:
        - Modulname
        - Gruppenname
        - Lehrveranstaltung
        - LV-Typ
        - ECTS
    • Speichert strukturierte Metadata für Retrieval und Filtering
    • Extrahiert zusätzlich alle LVA-Detailseiten-Links
      (Format: studienhandbuch.jku.at/XXXXXX)


Stufe 2 – Jede LVA-Detailseite (z.B. /188056):
  • VerantwortlicheR
  • Anmeldevoraussetzungen
  • Lernergebnisse, Kompetenzen, Fertigkeiten, Kenntnisse
  • Beurteilungskriterien, Lehrmethoden, Literatur
  • ECTS, Semesterstunden, Abhaltungssprache, Teilungsziffer

Ergebnis: statt 12 Chunks (nur Übersicht) → hunderte Chunks mit echtem Inhalt

MANIFEST-FORMAT (data/handbooks.json):
  [
    {
      "code":   "033/526",
      "name":   "Wirtschaftsinformatik",
      "degree": "Bachelor",
      "url":    "https://studienhandbuch.jku.at/curr/1193?lang=de"
    }
  ]

Abhängigkeiten: pip install requests beautifulsoup4 python-dotenv supabase
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client


from embeddings import EmbeddingService
from pipeline import get_or_create_study_program, supabase as _pipeline_supabase

load_dotenv()

MANIFEST_PATH   = "data/handbooks.json"
REQUEST_DELAY   = 1.0
REQUEST_TIMEOUT = 20
CHUNK_TABLE     = "chunks"
BASE_URL        = "https://studienhandbuch.jku.at"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JKU-StudyAssistant/1.0; "
        "educational-bot; +https://github.com/jku-study-assistant)"
    ),
    "Accept-Language": "de,en;q=0.9",
}

supabase: Client = _pipeline_supabase

LVA_TYPES = {"VL", "UE", "KV", "KS", "SE", "PR", "KT", "IK", "PJ", "PS", "PE", "VU", "VO", "KO", "AG"}
# ===============================================================================
# STUFE 1 - UEBERSICHTSSEITE
# ===============================================================================

def fetch_html(url: str) -> Optional[str]:
    """Laedt eine URL und gibt das rohe HTML zurueck. None bei Fehler."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"    Fehler beim Laden von {url}: {e}")
        return None



"""
Extrahiert die hierarchische Struktur der Studienplan-Uebersicht.

Die JKU-Studienhandbuch-Seite verwendet eine verschachtelte
Darstellung:

  Modul
    Gruppe/Fach
      VL/UE/KS/...

Diese Funktion erzeugt strukturierte Overview-Chunks fuer:
  • Module
  • Gruppen
  • konkrete Lehrveranstaltungen

Zusätzlich werden strukturierte Metadata gespeichert:
  • module_name
  • course_name
  • lva_name
  • course_type
  • ects
  • overview_level
"""

def extract_overview_rows(html: str, degree_name: str, degree_type: str):
    soup = BeautifulSoup(html, "html.parser")

    rows = []
    current_module = None
    current_group = None



    for tr in soup.find_all("tr"):
            cells = [
                td.get_text(" ", strip=True)
                for td in tr.find_all(["td", "th"])
            ]

            if len(cells) != 2:
                continue

            title = cells[0].strip()
            ects = cells[1].strip()

            if not ects.replace(",", "").replace(".", "").isdigit():
                continue

            clean_title = title.replace(".", "").strip()
            parts = clean_title.split()
            first_word = parts[0] if parts else ""

            is_lva = first_word in LVA_TYPES

            # Level 1: Modul
            if not title.startswith("."):
                current_module = clean_title
                current_group = None

                content = (
                    f"Studium: {degree_name}. Typ: {degree_type}. "
                    f"Modul: {current_module}. ECTS: {ects}."
                )

                rows.append({
                    "content": content,
                    "metadata": {
                        "study_program": degree_name,
                        "degree": degree_type,
                        "overview_level": "module",
                        "module_name": current_module,
                        "course_name": None,
                        "course_type": None,
                        "ects": ects,
                    }
                })

            # Level 3: Lehrveranstaltung
            # Wichtig: Einige LVAs haben keine Gruppe und stehen deshalb auf derselben
            # Einrückungsebene wie Gruppen. Deshalb wird LVA über den Typ erkannt.
            elif is_lva:
                course_type = first_word

                link_tag = tr.find("a", href=True)
                lva_url = None

                if link_tag:
                    href = link_tag["href"].strip()

                    if href.startswith("http"):
                        lva_url = href
                    elif href.startswith("/"):
                        lva_url = f"{BASE_URL}{href}"

                content = (
                    f"Studium: {degree_name}. Typ: {degree_type}. "
                    f"Modul: {current_module}. Gruppe: {current_group}. "
                    f"Lehrveranstaltung: {clean_title}. ECTS: {ects}."
                )

                rows.append({
                    "content": content,
                    "metadata": {
                        "study_program": degree_name,
                        "degree": degree_type,
                        "overview_level": "lva",
                        "module_name": current_module,
                        "course_name": current_group,
                        "course_type": course_type,
                        "lva_name": clean_title,
                        "lva_url": lva_url,
                        "ects": ects,
                    }
                })

            # Level 2: Gruppe / Fach
            else:
                current_group = clean_title

                content = (
                    f"Studium: {degree_name}. Typ: {degree_type}. "
                    f"Modul: {current_module}. Gruppe: {current_group}. ECTS: {ects}."
                )

                rows.append({
                    "content": content,
                    "metadata": {
                        "study_program": degree_name,
                        "degree": degree_type,
                        "overview_level": "group",
                        "module_name": current_module,
                        "course_name": current_group,
                        "course_type": None,
                        "ects": ects,
                    }
                })

    return rows








# ===============================================================================
# STUFE 2 - LVA-DETAILSEITEN
# ===============================================================================

def extract_lva_chunks(
    html: str,
    url: str,
    degree_name: str,
    degree_type: str,
    overview_metadata: dict | None = None,
) -> list[dict]:
    """
    Extrahiert strukturierte semantische Chunks aus einer LVA-Detailseite.

    WICHTIG:
    - Nur vorhandene Felder/Sektionen werden gespeichert
    - Metadata aus Ebene 1 werden uebernommen
    """

    soup = BeautifulSoup(html, "html.parser")



    # Unnoetige Bereiche entfernen
    for tag in soup.select(
        "nav, header, footer, script, style, form, "
        ".menu, #sidebar, .loginbox"
    ):
        tag.decompose()

    chunks = []

    def clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()




    def add_chunk(
        section: str,
        value: str,
        extra_meta: dict | None = None,
    ) -> None:
        """
        Fuegt nur sinnvolle/nicht-leere Chunks hinzu.
        """
        value = clean(value)
        if not value or len(value) < 3:
            return

        metadata = {
            "study_program": degree_name,
            "degree": degree_type,
            "source_type": "lva_detail",
            "source_url": url,
            "section": section,
        }

        # Metadata aus Ebene 1 uebernehmen
        if overview_metadata:
            metadata.update(overview_metadata)

        # Zusatz-Metadata
        if extra_meta:
            metadata.update(extra_meta)

        lva_name = metadata.get("lva_name", "Unbekannte Lehrveranstaltung")

        content = (
            f"Studium: {degree_name}. "
            f"Typ: {degree_type}. "
            f"Lehrveranstaltung: {lva_name}. "
            f"Abschnitt: {section}. "
            f"{section}: {value}"
        )

        chunks.append({
            "content": content,
            "metadata": metadata,
        })

    def extract_between(text: str, start: str, end: str) -> str:
            pattern = re.compile(
                rf"{re.escape(start)}\s*(.*?)\s*{re.escape(end)}",
                re.DOTALL
            )
            match = pattern.search(text)
            return clean(match.group(1)) if match else ""

    # ---------------------------------------------------------------------------
    # 1. Titel extrahieren
    # ---------------------------------------------------------------------------

    title_text = ""

    h1 = soup.find(["h1", "h2"])
    if h1:
        title_text = clean(h1.get_text(" ", strip=True))

    if not title_text:
        title_tag = soup.find("title")
        if title_tag:
            title_text = clean(
                title_tag.get_text(" ", strip=True)
                .replace("Studienhandbuch |", "")
            )

    # ---------------------------------------------------------------------------
    # 2. Tabellenfelder sammeln
    # ---------------------------------------------------------------------------

    fields = {}

    # Header/Value-Tabelle auf LVA-Seiten erkennen
    # Beispiel:
    # Workload | Ausbildungslevel | Studienfachbereich | VerantwortlicheR | Semesterstunden | Anbietende Uni
    # 3 ECTS   | B2 - Bachelor... | Wirtschaftsinformatik | Michael Schrefl | 2 SSt | JKU

    for tr in soup.find_all("tr"):
        cells = [
            clean(c.get_text(" ", strip=True))
            for c in tr.find_all(["td", "th"], recursive=False)
        ]
        cells = [c for c in cells if c]

        if "Workload" in cells and "VerantwortlicheR" in cells:
            next_tr = tr.find_next_sibling("tr")
            if next_tr:
                values = [
                    clean(c.get_text(" ", strip=True))
                    for c in next_tr.find_all(["td", "th"], recursive=False)
                ]
                values = [v for v in values if v]

                if len(values) == len(cells):
                    for key, value in zip(cells, values):
                        fields[key] = value

    for tr in soup.find_all("tr"):

        cells = tr.find_all(["td", "th"], recursive=False)

        if not cells:
            continue

        # Klassische Key-Value Zeilen
        if len(cells) == 2:

            label = clean(cells[0].get_text(" ", strip=True))
            value = clean(cells[1].get_text(" ", strip=True))

            if label and value:
                    if label not in [
                        "Kompetenzen",
                        "Fertigkeiten",
                        "Kenntnisse",
                    ]:
                        fields[label] = value


        # Tabellen mit mehreren Spalten
        elif len(cells) > 2:

            texts = [
                clean(c.get_text(" ", strip=True))
                for c in cells
            ]

            texts = [t for t in texts if t]

            if texts:
                joined = " | ".join(texts)

                if "ECTS" in joined or "SSt" in joined or "Workload" in joined:
                    fields["Metadaten"] = joined

    # ---------------------------------------------------------------------------
    # 3. Basisinformationen-Chunk
    # ---------------------------------------------------------------------------

    basis_info = []

    if title_text:
        basis_info.append(title_text)

    if "Metadaten" in fields:
        basis_info.append(fields["Metadaten"])

    if "Quellcurriculum" in fields:
        basis_info.append(fields["Quellcurriculum"])

    if basis_info:
        add_chunk(
            "Basisinformationen",
            " ".join(basis_info)
        )

    for label in [
        "Workload",
        "Ausbildungslevel",
        "Studienfachbereich",
        "VerantwortlicheR",
        "Semesterstunden",
        "Anbietende Uni",
    ]:
        if label in fields:
            add_chunk(label, fields[label])

    # ---------------------------------------------------------------------------
    # 4. Bekannte Sektionen
    # ---------------------------------------------------------------------------

    section_labels = [
        "Anmeldevoraussetzungen",
        "Quellcurriculum",
        "Kompetenzen",
        "Fertigkeiten",
        "Kenntnisse",
        "Beurteilungskriterien",
        "Lehrmethoden",
        "Abhaltungssprache",
        "Kursunterlagen",
        "Literatur",
        "Lehrinhalte wechselnd?",
        "Sonstige Informationen",
        "Frühere Varianten",
        "Teilungsziffer",
        "Zuteilungsverfahren",
    ]

    for label in section_labels:

        if label in fields:

            add_chunk(
                label,
                fields[label]
            )

    # ---------------------------------------------------------------------------
    # 4a. Lernergebnisse-Untersektionen
    # ---------------------------------------------------------------------------

    full_text = soup.get_text("\n", strip=True)

    lernergebnisse_block = extract_between(
        full_text,
        "Lernergebnisse",
        "Beurteilungskriterien"
    )

    if lernergebnisse_block:
        kompetenzen_text = extract_between(
            lernergebnisse_block,
            "Kompetenzen",
            "Fertigkeiten"
        )

        lo_items = re.findall(
            r"(LO\d+:\s.*?)(?=\s+LO\d+:|\Z)",
            lernergebnisse_block,
            flags=re.DOTALL
        )

        if "VL Einführung in die Softwareentwicklung" in title_text:
            print("\nDEBUG LERNERGEBNISSE BLOCK")
            print(lernergebnisse_block)
            print("\nDEBUG LO ITEMS")
            print(lo_items)

        fertigkeiten_items = []
        kenntnisse_items = []

        for item in lo_items:
            item_clean = clean(item)

            if item_clean.startswith("LO1:"):
                kenntnisse_items.append(item_clean)
            else:
                fertigkeiten_items.append(item_clean)

        if kompetenzen_text:
            add_chunk(
                "Lernergebnisse",
                kompetenzen_text,
                {"subsection": "Kompetenzen"}
            )

        if fertigkeiten_items:
            add_chunk(
                "Lernergebnisse",
                "\n".join(fertigkeiten_items),
                {"subsection": "Fertigkeiten"}
            )

        if kenntnisse_items:
            add_chunk(
                "Lernergebnisse",
                "\n".join(kenntnisse_items),
                {"subsection": "Kenntnisse"}
            )

        combined_parts = []

        if kompetenzen_text:
            combined_parts.append(f"Kompetenzen: {kompetenzen_text}")

        if fertigkeiten_items:
            combined_parts.append("Fertigkeiten:\n" + "\n".join(fertigkeiten_items))

        if kenntnisse_items:
            combined_parts.append("Kenntnisse:\n" + "\n".join(kenntnisse_items))

        if combined_parts:
            add_chunk(
                "Lernergebnisse",
                "\n\n".join(combined_parts),
                {"subsection": "Alle"}
            )








    return chunks





# ===============================================================================
# SUPABASE
# ===============================================================================

INSERT_BATCH_SIZE = 50   # Rows pro INSERT-Request (Supabase-Limit: ~500, konservativ)

def _chunks_exist_for_program(study_program_id: str) -> bool:
    """Prueft ob fuer diesen Studiengang bereits Handbook-Chunks vorhanden sind."""
    result = (
        supabase.table("documents")
        .select("id")
        .eq("study_program_id", study_program_id)
        .eq("status", "processed")
        .like("filename", "handbook_%")
        .execute()
    )
    return len(result.data) > 0


def _create_document(study_program_id: str, source_label: str) -> str:
    """Legt einen Dokument-Eintrag an und gibt die ID zurueck."""
    doc_result = supabase.table("documents").insert({
        "user_id":          None,
        "filename":         source_label,
        "bucket_path":      None,
        "study_program_id": study_program_id,
        "status":           "processing",
    }).execute()
    return doc_result.data[0]["id"]


def _batch_insert_chunks(
    chunks: list[str],
    embeddings: list[list[float]],
    sources: list[str],
    document_id: str,
    chunk_type: str,
    chunk_offset: int,
    extra_metadata: list[dict] | None = None,
) -> int:
    """
    Speichert Chunks in Batches statt einzeln.

    Einzelne INSERTs bei 4000+ Chunks fuehren zu Server-Disconnects.
    Batch-INSERTs reduzieren die Anzahl der Requests um Faktor INSERT_BATCH_SIZE.

    :returns: Anzahl erfolgreich gespeicherter Chunks
    """
    total_saved = 0
    rows = []

    for i, (chunk, vector, src) in enumerate(zip(chunks, embeddings, sources)):
        metadata = {
            "source_type": chunk_type,
            "source_url": src,
            "chunk_index": chunk_offset + i,
            "chunk_type": chunk_type,
            "has_table": "|" in chunk,
        }

        if extra_metadata and i < len(extra_metadata):
            metadata.update(extra_metadata[i])

        rows.append({
            "content": chunk,
            "embedding": vector,
            "document_id": document_id,
            "metadata": metadata
        })

    for batch_start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[batch_start: batch_start + INSERT_BATCH_SIZE]
        try:
            supabase.table(CHUNK_TABLE).insert(batch).execute()
            total_saved += len(batch)
        except Exception as e:
            print(f"      Batch {batch_start // INSERT_BATCH_SIZE + 1} Fehler: {e}")

            for row in batch:
                try:
                    supabase.table(CHUNK_TABLE).insert(row).execute()
                    total_saved += 1
                except Exception:
                    pass

    return total_saved


# ===============================================================================
# HAUPT-ORCHESTRIERUNG
# ===============================================================================

def scrape_program(entry: dict, embed_service: EmbeddingService) -> int:
    """
    Scrapt einen Studiengang zweistufig und speichert alle Chunks in Supabase.

    ABLAUF:
      1. Studiengang anlegen (get_or_create) + Duplikat-Check
      2. Dokument-Eintrag anlegen
      3. Uebersichtsseite laden -> Text + LVA-Links extrahieren
      4. Uebersichtstext chunken + embedden + speichern
      5. Jede LVA-Detailseite laden -> Text extrahieren
      6. Alle LVA-Texte gesammelt chunken + embedden + speichern
      7. Dokument-Status -> "processed"
    """
    code    = entry["code"]
    name    = entry["name"]
    degree  = entry.get("degree")
    url     = entry["url"]
    source_label = f"handbook_{code.replace('/', '-')}"

    print(f"\n📚 Verarbeite: {code} - {name} ({degree or 'unbekannt'})")

    program_id = get_or_create_study_program(code, name, degree)

    #if _chunks_exist_for_program(program_id):
        #print(f"   Bereits vorhanden - ueberspringe.")
        #return 0

    document_id = _create_document(program_id, source_label)

    try:
        total_saved  = 0
        chunk_offset = 0

        # Stufe 1: Uebersichtsseite
        print(f"   Lade Uebersichtsseite...")
        overview_html = fetch_html(url)

        if not overview_html:
            raise ValueError(f"Uebersichtsseite nicht erreichbar: {url}")

        # Neue strukturierte Overview-Extraktion
        overview_rows = extract_overview_rows(overview_html, name, degree)

        lva_urls = [
            row["metadata"]["lva_url"]
            for row in overview_rows
            if row["metadata"].get("lva_url")
        ]

        print(f"   {len(lva_urls)} LVA-Detailseiten gefunden.")

        overview_metadata_by_url = {}

        for row in overview_rows:
            metadata = row.get("metadata", {})
            lva_url = metadata.get("lva_url")

            if lva_url:
                overview_metadata_by_url[lva_url] = metadata




        if overview_rows:
            ov_chunks = [r["content"] for r in overview_rows]
            ov_metadata = [r["metadata"] for r in overview_rows]

            print(f"   Generiere Embeddings fuer {len(ov_chunks)} Overview-Chunks...")
            ov_embeddings = embed_service.embed_texts(ov_chunks)



            saved = _batch_insert_chunks(
                ov_chunks,
                ov_embeddings,
                [url] * len(ov_chunks),
                document_id,
                "overview",
                chunk_offset,
                extra_metadata=ov_metadata,
            )

            total_saved += saved
            chunk_offset += len(ov_chunks)

            print(f"   Uebersicht: {saved} Chunks gespeichert.")
        else:
            print("   Keine strukturierten Overview-Zeilen gefunden.")


        # Stufe 2: LVA-Detailseiten
        print(f"   Scrape {len(lva_urls)} von {len(lva_urls)} LVA-Seiten zum Test...")

        all_lva_chunks: list[str] = []
        all_lva_sources: list[str] = []
        all_lva_metadata: list[dict] = []

        for i, lva_url in enumerate(lva_urls, 1):
            time.sleep(REQUEST_DELAY)

            lva_html = fetch_html(lva_url)

            if not lva_html:
                continue




            lva_items = extract_lva_chunks(
                lva_html,
                lva_url,
                name,
                degree,
                overview_metadata=overview_metadata_by_url.get(lva_url),
            )

            for item in lva_items:
                all_lva_chunks.append(item["content"])
                all_lva_sources.append(lva_url)
                all_lva_metadata.append(item["metadata"])

            print(f"      {i}/{len(lva_items)} LVAs geladen...")

        if all_lva_chunks:
            print(f"   Generiere Embeddings fuer {len(all_lva_chunks)} LVA-Chunks...")

            lva_embeddings = embed_service.embed_texts(all_lva_chunks)

            saved = _batch_insert_chunks(
                all_lva_chunks,
                lva_embeddings,
                all_lva_sources,
                document_id,
                "lva_detail",
                chunk_offset,
                extra_metadata=all_lva_metadata,
            )

            total_saved += saved

            print(f"   LVA-Chunks: {saved}/{len(all_lva_chunks)} gespeichert.")

        else:
            print("   Keine LVA-Chunks gefunden.")

        supabase.table("documents").update({
            "status": "processed"
        }).eq("id", document_id).execute()

        print(
            f"   Fertig: {total_saved} Chunks gespeichert "
            f"({len(lva_urls)} LVA-Seiten)"
        )

        return total_saved

    except Exception as e:
        supabase.table("documents").update({"status": "error"}).eq("id", document_id).execute()
        print(f"   Fehler: {e}")
        raise


def run_scraper(manifest_path: str = MANIFEST_PATH) -> None:
    """Liest das Manifest und scrapt alle darin aufgefuehrten Studienganege."""
    if not os.path.exists(manifest_path):
        print(f"Manifest nicht gefunden: {manifest_path}")
        return

    with open(manifest_path, encoding="utf-8") as f:
        entries = json.load(f)

    if not entries:
        print("Manifest ist leer.")
        return

    print(f"Starte Scraping fuer {len(entries)} Studiengaenge...")
    embed_service = EmbeddingService()

    total_chunks  = 0
    success_count = 0
    error_count   = 0

    for entry in entries:
        try:
            n = scrape_program(entry, embed_service)
            total_chunks  += n
            success_count += 1
        except Exception as e:
            print(f"   FEHLER bei {entry.get('name')}: {e}")
            error_count += 1

    print("\n" + "=" * 60)
    print(f"Fertig! {success_count} erfolgreich, {error_count} Fehler.")
    print(f"Gesamt: {total_chunks} Chunks in Supabase gespeichert.")


if __name__ == "__main__":
    run_scraper()