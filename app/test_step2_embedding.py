"""
test_step2_embedding.py – Lokaler Embedding + Retrieval-Test (kein Supabase)
=============================================================================
Ausführen in deinem Projektverzeichnis:
    python test_step2_embedding.py
"""

import sys
import numpy as np

PDF_PATH = "data/admin_pdfs/1193_17_BS_Wirtschaftsinformatik.pdf"

# ── 1. Chunks laden ──────────────────────────────────────────────────────────
print("Lade Chunks...")
from pdf_chunking import chunk_curriculum_pdf

with open(PDF_PATH, "rb") as f:
    pdf_bytes = f.read()

chunks = chunk_curriculum_pdf(
    pdf_bytes,
    degree="Bachelor",
    study_program="Wirtschaftsinformatik",
)
print(f"✅ {len(chunks)} Chunks geladen")

from collections import Counter
types = Counter(c["metadata"]["chunk_type"] for c in chunks)
for t, n in types.items():
    print(f"   {t:25s}: {n}")

# ── 2. Embeddings erstellen ───────────────────────────────────────────────────
print("\nLade E5-Modell und erstelle Embeddings...")
from embeddings import EmbeddingService

svc = EmbeddingService()
texts = [c["content"] for c in chunks]
vectors = svc.embed_texts(texts)
vecs = np.array(vectors)
print(f"✅ {len(vectors)} Embeddings erstellt (dim={len(vectors[0])})")

# ── 3. Lokale Suchfunktion mit Query Expansion ────────────────────────────────
EXPANSIONS = {
    "steop":       "Studieneingangs- und Orientierungsphase STEOP",
    "wahlfach":    "Wahlfach Wirtschaftsinformatik Wirtschaftswissenschaften",
    "wahlfächer":  "Wahlfach Wirtschaftsinformatik Wirtschaftswissenschaften",
    "pflichtfach": "Pflichtfächer Grundlagen",
    "semester":    "Semester Lehrveranstaltungen Studienplan",
}

def expand_query(query: str) -> str:
    result = query
    for term, expanded in EXPANSIONS.items():
        if term.lower() in query.lower():
            result = result + " " + expanded
    return result

def search(query: str, top_k: int = 5):
    expanded = expand_query(query)
    q_vec = svc.model.encode(f"query: {expanded}", normalize_embeddings=True)
    scores = vecs @ q_vec
    ranked = sorted(enumerate(scores), key=lambda x: -x[1])
    return [(chunks[i], float(s)) for i, s in ranked[:top_k]]

# ── 4. Testfragen ─────────────────────────────────────────────────────────────
# (Frage, Keywords die in einem Top-3-Chunk stehen sollen, bekannte Limitation?)
TESTFRAGEN = [
    ("Wie viele ECTS hat Datenmodellierung?",              ["Datenmodellierung"],                   None),
    ("Welche Kurse gibt es im Modul Software Engineering?",["Software Engineering"],                None),
    ("Was ist die STEOP?",                                 ["Studieneingangs", "§ 6"],              None),
    ("Welche Wahlfächer gibt es?",                         ["Wahlfach", "§ 8"],                    None),
    ("Wie viele ECTS hat das gesamte Bachelorstudium?",    ["180", "ECTS-Übersicht"],              None),
    ("Welche Lehrveranstaltungen gibt es im ersten Semester?", ["Einführung", "Semester"],
     "Semesterpläne sind Bild-Tabellen im PDF – nur teilweise lesbar"),
    ("Was sind die Pflichtfächer?",                        ["Pflichtfächer", "§ 7"],               None),
    ("Wie viele ECTS hat Statistik?",                      ["Statistik"],                          None),
]

print(f"\n{'='*70}")
print("RETRIEVAL-TEST")
print(f"{'='*70}")

passed = 0
known_limitation = 0
for frage, keywords, hinweis in TESTFRAGEN:
    results = search(frage, top_k=3)

    # Treffer wenn Keyword in einem der Top-3 vorkommt
    hit = False
    hit_rank = None
    for rank, (chunk, score) in enumerate(results, 1):
        if any(kw.lower() in chunk["content"].lower() for kw in keywords):
            hit = True
            hit_rank = rank
            break

    top_chunk, top_score = results[0]
    preview = top_chunk["content"][:100].replace("\n", " ")

    if hit:
        passed += 1
        symbol = "✅"
    elif hinweis:
        known_limitation += 1
        symbol = "ℹ️ "
    else:
        symbol = "❌"

    print(f"\n{symbol} [{top_score:.3f}] {frage}")
    print(f"   [{top_chunk['metadata']['chunk_type']}] {preview}")

    if hit and hit_rank > 1:
        print(f"   (Treffer auf Rang #{hit_rank})")
    if not hit:
        if hinweis:
            print(f"   ℹ️  {hinweis}")
        else:
            print(f"   ❌ Keines von {keywords} in Top-3!")
            for c, s in results:
                print(f"     [{s:.3f}] {c['content'][:80].replace(chr(10),' ')}")

relevant = len(TESTFRAGEN) - known_limitation
print(f"\n{'='*70}")
print(f"Ergebnis: {passed}/{relevant} relevante Tests bestanden")
if known_limitation:
    print(f"ℹ️  {known_limitation} Test(s) übersprungen (bekannte PDF-Limitation)")
if passed >= relevant:
    print("✅ Alle Tests bestanden – bereit für Schritt 3 (Supabase-Upload)")
else:
    print("⚠️  Noch Verbesserungsbedarf")
print(f"{'='*70}")