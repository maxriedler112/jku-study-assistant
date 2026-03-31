from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List
import fitz  # PyMuPDF
from chunking import chunk_text
from embeddings import EmbeddingService

# Konfiguration
PDF_FILE = "1193_17_BS_Wirtschaftsinformatik.pdf"
PDF_PATH = Path("data") / PDF_FILE
OUTPUT_PATH = Path("data/chunks_with_embeddings.json")

def extract_pages(pdf_path: Path) -> List[Dict]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF nicht gefunden: {pdf_path}")

    doc = fitz.open(pdf_path)
    pages = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text", sort=True)
        if text.strip():
            pages.append({"page": page_num, "text": text})
    return pages

def build_chunks(pages: List[Dict], source_name: str) -> List[Dict]:
    all_chunks = []
    for page_data in pages:
        page_chunks = chunk_text(page_data["text"], chunk_size=1000, overlap=200)
        
        for idx, chunk in enumerate(page_chunks):
            all_chunks.append({
                "content": chunk,  # 'content' ist der Standardname in pgvector Tutorials
                "metadata": {
                    "source": source_name,
                    "page": page_data["page"],
                    "chunk_index": idx
                }
            })
    return all_chunks

def main() -> None:
    print(f"--- Starte Ingest für: {PDF_FILE} ---")
    
    # 1. Extraktion
    pages = extract_pages(PDF_PATH)
    
    # 2. Chunking (Wir nutzen den Dateinamen als Source)
    chunks = build_chunks(pages, source_name=PDF_FILE)
    print(f"Erstellt: {len(chunks)} Chunks.")

    # 3. Embeddings
    embedder = EmbeddingService()
    texts = [c["content"] for c in chunks]
    vectors = embedder.embed_texts(texts)

    # Vektoren in die Struktur einfügen
    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector

    # 4. Speichern (Lokal als Backup/Test)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    
    print(f"Erfolg! {len(chunks)} Vektoren lokal in {OUTPUT_PATH} gespeichert.")
    print("\nNächster Schritt: Upload der JSON zu Supabase.")

if __name__ == "__main__":
    main()