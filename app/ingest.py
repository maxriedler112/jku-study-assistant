from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF

from chunking import chunk_text, clean_text
from embeddings import EmbeddingService


PDF_PATH = Path("data/1193_17_BS_Wirtschaftsinformatik.pdf")
OUTPUT_PATH = Path("data/chunks_with_embeddings.json")


def extract_pages(pdf_path: Path) -> List[Dict]:
    print(f"[DEBUG] Prüfe PDF-Pfad: {pdf_path.resolve()}")

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print("[DEBUG] Öffne PDF...")
    doc = fitz.open(pdf_path)
    print(f"[DEBUG] PDF geöffnet. Seitenanzahl: {len(doc)}")

    pages: List[Dict] = []

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text", sort=True)
        text = clean_text(text)

        print(f"[DEBUG] Seite {page_num}: {len(text)} Zeichen extrahiert")

        if text:
            pages.append(
                {
                    "page": page_num,
                    "text": text,
                }
            )

    return pages


def build_chunks(pages: List[Dict]) -> List[Dict]:
    all_chunks: List[Dict] = []

    for page_data in pages:
        page_num = page_data["page"]
        page_text = page_data["text"]

        page_chunks = chunk_text(
            page_text,
            chunk_size=1000,
            overlap=200,
        )

        print(f"[DEBUG] Seite {page_num}: {len(page_chunks)} Chunks erstellt")

        for idx, chunk in enumerate(page_chunks):
            all_chunks.append(
                {
                    "source": "WIN Curriculum",
                    "page": page_num,
                    "chunk_index": idx,
                    "text": chunk,
                }
            )

    return all_chunks


def main() -> None:
    print("=== INGEST START ===")

    try:
        print("1) Extracting text from PDF...")
        pages = extract_pages(PDF_PATH)
        print(f"   Extracted {len(pages)} pages with text")

        if not pages:
            print("[WARNUNG] Keine Seiten mit Text gefunden.")
            return

        print("2) Building chunks...")
        chunks = build_chunks(pages)
        print(f"   Built {len(chunks)} chunks")

        if not chunks:
            print("[WARNUNG] Keine Chunks erstellt.")
            return

        print("3) Generating embeddings...")
        embedder = EmbeddingService()
        texts = [chunk["text"] for chunk in chunks]
        vectors = embedder.embed_texts(texts)

        print(f"[DEBUG] Embeddings erzeugt: {len(vectors)}")

        for chunk, vector in zip(chunks, vectors):
            chunk["embedding"] = vector

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        print(f"Done. Saved output to: {OUTPUT_PATH.resolve()}")
        print("=== INGEST ENDE ===")

    except Exception as e:
        print(f"[FEHLER] {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()