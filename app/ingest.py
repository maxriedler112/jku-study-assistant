import os
import json
import pdfplumber
from chunking import chunk_text
from embeddings import EmbeddingService

def run_ingest():
    # 1. Pfade festlegen (basierend auf deinem Screenshot)
    pdf_path = "data/1193_17_BS_Wirtschaftsinformatik.pdf"
    output_path = "data/chunks_with_embeddings.json"

    if not os.path.exists(pdf_path):
        print(f"❌ Fehler: Das PDF wurde unter {pdf_path} nicht gefunden!")
        return

    # 2. PDF Text extrahieren
    print(f"📄 Extrahiere Text aus: {pdf_path}...")
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if not page_text:
                continue
            # Inhaltsverzeichnis-Seiten überspringen (viele Leitpunkte)
            if page_text.count(". .") > 8:
                continue
            full_text += page_text + "\n"

    # 3. Text in Chunks unterteilen
    print("✂️ Erstelle Text-Abschnitte (Chunks)...")
    chunks = chunk_text(full_text)
    
    # 4. Embeddings generieren
    print(f"🧠 {len(chunks)} Chunks gefunden. Generiere 768-dimensionale Vektoren...")
    embed_service = EmbeddingService()
    embeddings = embed_service.embed_texts(chunks)

    # 5. Daten für Supabase strukturieren
    final_data = []
    for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        final_data.append({
            "content": chunk,
            "embedding": vector,
            "metadata": {
                "source": "1193_17_BS_Wirtschaftsinformatik.pdf",
                "chunk_index": i
            }
        })

    # 6. Speichern der fertigen Datei
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)
    
    print(f"✅ Erfolg! Die Datei {output_path} wurde erstellt.")

if __name__ == "__main__":
    run_ingest()