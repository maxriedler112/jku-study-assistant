"""
handbook_scraper.py – Zweistufiger Admin-Scraper für das JKU Studienhandbuch.
==============================================================================

SCRAPING-STRATEGIE (zweistufig):
---------------------------------
Stufe 1 – Übersichtsseite (z.B. /curr/1193):
  • Enthält die komplette Modulstruktur als Tabelle (Modulname, ECTS, LV-Typ)
  • Extrahiert alle LVA-Links (Format: studienhandbuch.jku.at/XXXXXX)

Stufe 2 – Jede LVA-Detailseite (z.B. /188056):
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

from chunking import chunk_text
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


def extract_lva_links(html: str) -> list[str]:
    """
    Extrahiert alle LVA-Detailseiten-Links aus der Uebersichtsseite.
    LVA-Links haben das Format: https://studienhandbuch.jku.at/XXXXXX
    wobei XXXXXX eine reine Zahl ist (z.B. /188056).
    """
    soup = BeautifulSoup(html, "html.parser")

    print("DEBUG table count:", len(soup.find_all("table")))

    for idx, tr in enumerate(soup.find_all("tr")[:40]):
        cells = [
            td.get_text(separator=" ", strip=True)
            for td in tr.find_all(["td", "th"])
        ]
        print(f"ROW {idx}: {cells}")
    lva_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if re.match(r'^https?://studienhandbuch\.jku\.at/\d+$', href):
            lva_urls.add(href)
        elif re.match(r'^/\d+$', href):
            lva_urls.add(f"{BASE_URL}{href}")

    return sorted(lva_urls)


def extract_overview_text(html: str, program_name: str) -> str:
    """
    Extrahiert den Strukturtext der Uebersichtsseite (Modulbaum + ECTS-Tabelle).
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.select("nav, header, footer, script, style, .menu, "
                           "#sidebar, .breadcrumb, form"):
        tag.decompose()

    content_table = soup.find("table", recursive=True)
    if not content_table:
        return ""

    rows = []
    for tr in content_table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))

    if not rows:
        return ""

    return f"STUDIENPLAN {program_name.upper()}\n\n" + "\n".join(rows)

def extract_overview_rows(html: str, degree_name: str, degree_type: str):
    soup = BeautifulSoup(html, "html.parser")

    rows = []
    current_module = None
    current_group = None

    course_types = {"VL", "UE", "KV", "KS", "SE", "PR", "KT", "IK", "PJ", "PS", "PE"}

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

        # Level 2: Gruppe / Fach innerhalb eines Moduls
        elif title.startswith("........") and not title.startswith("................"):
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

        # Level 3: konkrete Lehrveranstaltung
        elif title.startswith("................"):
            course_type = first_word if first_word in course_types else None

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
                    "ects": ects,
                }
            })

    return rows







# ===============================================================================
# STUFE 2 - LVA-DETAILSEITEN
# ===============================================================================

def extract_lva_text(html: str, url: str) -> str:
    """
    Extrahiert den Inhalt einer LVA-Detailseite sauber und ohne Duplikate.

    KERNPROBLEM: Das Studienhandbuch hat verschachtelte Tabellen.
    find_all("table") + find_all("tr") durchlaeuft innere Tabellen mehrfach
    weil die aeussere Tabelle die inneren als Kinder enthaelt.

    LOESUNG: Nur direkte Kind-Rows (<tr>) jeder Tabelle verarbeiten
    (recursive=False), und nur die innerste relevante Tabelle nutzen.
    Zusaetzlich: seen_values Set verhindert inhaltliche Duplikate.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Navigation und irrelevante Elemente entfernen
    for tag in soup.select("nav, header, footer, script, style, form, "
                           ".menu, #sidebar, .loginbox"):
        tag.decompose()

    parts: list[str] = []
    seen_values: set[str] = set()  # Verhindert inhaltliche Duplikate

    def add_part(text: str) -> None:
        """Fuegt Text nur hinzu wenn er noch nicht vorhanden ist."""
        key = text[:80]  # Ersten 80 Zeichen als Duplikat-Schluessel
        if key not in seen_values and len(text) > 3:
            seen_values.add(key)
            parts.append(text)

    # ── 1. LV-Titel ──────────────────────────────────────────────────────────
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True).replace("Studienhandbuch | ", "").strip()
        if title and title != "Studienhandbuch":
            add_part(f"LEHRVERANSTALTUNG: {title}")

    # ── 2. Breadcrumb ────────────────────────────────────────────────────────
    breadcrumb = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/curr/" in href or re.match(r".*studienhandbuch\.jku\.at/\d+", href):
            text = a.get_text(strip=True)
            if text and len(text) > 3 and text not in breadcrumb:
                breadcrumb.append(text)
    if breadcrumb:
        add_part("Studiengang-Kontext: " + " > ".join(breadcrumb[:5]))

    # ── 3. Nur direkte Kind-Rows verarbeiten (kein rekursives find_all) ──────
    skip_labels = {
        "versionsauswahl", "version", "inhalt", "detailinformationen",
        "lernergebnisse", "positionsanzeige", "sprachauswahl", "sprache",
        "menue", "seitenbereiche", "externe tools", "studienhandbuch-login",
        "praesenzlehrveranstaltung", "", "versionsauswahl version",
    }
    seen_labels: set[str] = set()

    for table in soup.find_all("table"):
        # Nur direkte Kind-Rows - verhindert Mehrfachverarbeitung
        direct_rows = table.find_all("tr", recursive=False)
        if not direct_rows:
            # Manche Tabellen haben tbody als Zwischenschicht
            tbody = table.find("tbody")
            if tbody:
                direct_rows = tbody.find_all("tr", recursive=False)

        for row in direct_rows:
            # Nur direkte Kind-Zellen
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                continue

            if len(cells) == 2:
                label = re.sub(r"\s+", " ", cells[0].get_text()).strip()
                value = re.sub(r"\s+", " ", cells[1].get_text()).strip()

                if (label and value
                        and len(value) > 3
                        and label.lower() not in skip_labels
                        and label not in seen_labels):
                    seen_labels.add(label)
                    add_part(f"{label}: {value}")

            elif len(cells) > 2:
                texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
                texts = [t for t in texts if t and len(t) > 1]
                if texts and any(kw in " ".join(texts) for kw in ["ECTS", "SSt"]):
                    add_part("Metadaten: " + " | ".join(texts))

    # ── 4. Listen (LO1, LO2, Literatur etc.) ─────────────────────────────────
    for ul in soup.find_all(["ul", "ol"]):
        items = []
        for li in ul.find_all("li", recursive=False):
            text = re.sub(r"\s+", " ", li.get_text()).strip()
            if text and len(text) > 10:
                items.append(f"- {text}")
        if items:
            add_part("\n".join(items))

    return "\n\n".join(filter(None, parts))


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

    if _chunks_exist_for_program(program_id):
        print(f"   Bereits vorhanden - ueberspringe.")
        return 0

    document_id = _create_document(program_id, source_label)

    try:
        total_saved  = 0
        chunk_offset = 0

        # Stufe 1: Uebersichtsseite
        print(f"   Lade Uebersichtsseite...")
        overview_html = fetch_html(url)

        if not overview_html:
            raise ValueError(f"Uebersichtsseite nicht erreichbar: {url}")

        lva_urls = extract_lva_links(overview_html)
        print(f"   {len(lva_urls)} LVA-Detailseiten gefunden.")

        # Neue strukturierte Overview-Extraktion
        overview_rows = extract_overview_rows(overview_html, name, degree)

        print(f"   DEBUG overview_rows: {len(overview_rows)}")
        print("   DEBUG first 1000 chars overview_html:")
        print(overview_html[:1000])

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
        print(f"   Scrape {len(lva_urls)} LVA-Seiten...")

        all_lva_chunks:  list[str] = []
        all_lva_sources: list[str] = []

        for i, lva_url in enumerate(lva_urls, 1):
            time.sleep(REQUEST_DELAY)
            lva_html = fetch_html(lva_url)
            if not lva_html:
                continue

            lva_text = extract_lva_text(lva_html, lva_url)
            if lva_text.strip() and len(lva_text) > 100:
                chunks = chunk_text(lva_text)
                all_lva_chunks.extend(chunks)
                all_lva_sources.extend([lva_url] * len(chunks))

            if i % 20 == 0:
                print(f"      {i}/{len(lva_urls)} LVAs geladen...")

        if all_lva_chunks:
            print(f"   Generiere Embeddings fuer {len(all_lva_chunks)} LVA-Chunks...")
            lva_embeddings = embed_service.embed_texts(all_lva_chunks)
            saved = _batch_insert_chunks(
                all_lva_chunks, lva_embeddings, all_lva_sources,
                document_id, "lva_detail", chunk_offset,
            )
            total_saved += saved
            print(f"   LVA-Chunks: {saved}/{len(all_lva_chunks)} gespeichert.")

        supabase.table("documents").update({"status": "processed"}).eq("id", document_id).execute()
        print(f"   Fertig: {total_saved} Chunks gespeichert ({len(lva_urls)} LVAs).")
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