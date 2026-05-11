"""
web_scraper.py – JKU-Webseiten scrapen mit trafilatura.

Zweck:
  Extrahiert den Haupttext von JKU-Webseiten (ohne Navigation, Werbung, Footer).
  Der extrahierte Text kann direkt in dieselbe ETL-Pipeline wie PDFs eingespeist werden:
    scrape_jku_urls()  →  chunk_text()  →  EmbeddingService  →  Supabase

Voraussetzung: pip install trafilatura
"""
from __future__ import annotations

from typing import Optional
import trafilatura


def fetch_page_text(url: str) -> Optional[str]:
    """
    Lädt eine URL herunter und extrahiert den Haupttext-Inhalt.

    trafilatura erkennt automatisch den relevanten Inhalt und entfernt
    Navigation, Werbebanner, Footer usw.

    :param url: Vollständige URL, z.B. "https://www.jku.at/studium/..."
    :returns:   Extrahierter Text als String, oder None bei Fehler
    """
    # HTML der Seite herunterladen
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None

    # Hauptinhalt aus dem HTML extrahieren
    return trafilatura.extract(
        downloaded,
        include_tables=True,    # Tabellen (z.B. Lehrveranstaltungslisten) mitnehmen
        include_links=False,    # Hyperlinks weglassen (stören das Embedding)
        output_format="txt",    # Nur Klartext, kein HTML/Markdown
    )


def scrape_jku_urls(urls: list[str]) -> list[dict]:
    """
    Scrapt eine Liste von JKU-URLs und gibt die Ergebnisse als Dicts zurück.

    Leere oder fehlerhafte Seiten werden stillschweigend übersprungen.

    :param urls: Liste von URLs, die gescrapt werden sollen
    :returns:    Liste von {"url": str, "text": str} – bereit für chunk_text()

    Beispiel-Verwendung:
        pages = scrape_jku_urls(["https://www.jku.at/studium/..."])
        for page in pages:
            chunks = chunk_text(page["text"])
            # → weiter in die Pipeline einspeisen
    """
    results = []
    for url in urls:
        text = fetch_page_text(url)
        # Nur Seiten mit tatsächlichem Inhalt weitergeben
        if text and text.strip():
            results.append({"url": url, "text": text.strip()})
    return results


# ── Direktaufruf zum Testen ──────────────────────────────────────────────────
if __name__ == "__main__":
    # Beispiel-URLs für manuelle Tests
    sample_urls = [
        "https://www.jku.at/studium/studienrichtungen/bachelor/wirtschaftsinformatik/",
    ]

    pages = scrape_jku_urls(sample_urls)

    for page in pages:
        print(f"URL:   {page['url']}")
        print(f"Länge: {len(page['text'])} Zeichen")
        print("Vorschau:")
        print(page["text"][:500])
        print("---")
