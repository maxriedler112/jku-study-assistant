"""
seed_studienverlauf.py – Einmaliger Seed des idealtypischen Studienverlaufs (WI Bachelor).

Hintergrund: Die Semester-Tabelle steht im Curriculum-PDF als BILD (kein Textlayer)
und wurde daher beim automatischen Ingest nicht extrahiert (Eval #9). Dieses Skript
traegt die Tabelle (Beginn Wintersemester) manuell als saubere, durchsuchbare Chunks
in Supabase ein – ein Chunk pro Semester.

Idempotent: ein vorhandenes Seed-Dokument wird vorher entfernt und neu angelegt.

Start:  python app/seed_studienverlauf.py   (aus dem Projekt-Root, .env muss vorhanden sein)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # app/ auf den Pfad

from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(URL, KEY)

WI_PROGRAM_ID = "9d71571c-b521-44a4-b40a-f4041112e6c3"
FILENAME = "studienverlauf_idealtypisch_ws_manual"

# Idealtypischer Studienverlauf mit Beginn im Wintersemester (Curriculum 17_BS_WIN, Seite 8).
SEMESTERS = [
    (1, "Wintersemester", [
        ("Einführung in die Wirtschaftsinformatik", 6),
        ("Grundlagen der Betriebswirtschaftslehre und des integrierten Managements", 6),
        ("VL Einführung in die Informatik", 3),
        ("Einführung in die Softwareentwicklung", 6),
        ("Mathematik und Logik", 6),
        ("KS Kommunikative Fertigkeiten Englisch (B2)", 3),
    ]),
    (2, "Sommersemester", [
        ("Algorithmen und Datenstrukturen", 6),
        ("Prozess- und Kommunikationsmodellierung", 6),
        ("VL Operating Systems", 3),
        ("Vertiefung Softwareentwicklung", 6),
        ("Formale Grundlagen", 6),
        ("Freie Studienleistungen", 3),
    ]),
    (3, "Wintersemester", [
        ("Datenmodellierung", 6),
        ("Leistungserstellung und -verwertung", 6),
        ("Statistik", 3),
        ("IT-Project Engineering & Management", 6),
        ("Software Engineering – Methoden und Konzepte", 6),
        ("Freie Studienleistungen", 3),
    ]),
    (4, "Sommersemester", [
        ("Unternehmensrechnung", 6),
        ("Grundlagen des Rechts", 6),
        ("Informationsmanagement", 6),
        ("Software Engineering – Anwendungen", 6),
        ("Data & Knowledge Engineering – Methoden und Konzepte", 6),
    ]),
    (5, "Wintersemester", [
        ("KS Einführung in IKT, Gesellschaft, Gender und Diversity", 3),
        ("Data & Knowledge Engineering – Anwendungen", 6),
        ("Communications Engineering – Methoden und Konzepte", 6),
        ("IT-Projekt Wirtschaftsinformatik", 6),
        ("PS Ausgewählte Aspekte der Wirtschaftsinformatik + SE Fachsprache Englisch", 6),
        ("Freie Studienleistungen", 3),
    ]),
    (6, "Sommersemester", [
        ("KS Soziale Auswirkungen der IT", 3),
        ("Communications Engineering – Anwendungen", 6),
        ("PS Ausgewählte Aspekte der Wirtschaftsinformatik", 3),
        ("Spezialisierungsfach Wirtschaftsinformatik (mit Bachelorarbeit)", 12),
        ("Wahlfach Wirtschaftswissenschaften oder Wirtschaftsinformatik", 6),
    ]),
]


def build_chunk_text(nr: int, season: str, courses: list) -> str:
    lines = [
        "Studium: Wirtschaftsinformatik. Typ: Bachelor. "
        "Abschnitt: Idealtypischer Studienverlauf (Beginn im Wintersemester).",
        f"Im {nr}. Semester ({season}) werden laut empfohlenem Studienverlauf "
        f"folgende Lehrveranstaltungen empfohlen (insgesamt 30 ECTS):",
    ]
    for name, ects in courses:
        lines.append(f"- {name}: {ects} ECTS")
    return "\n".join(lines)


def cleanup_existing():
    docs = (
        supabase.table("documents")
        .select("id")
        .eq("filename", FILENAME)
        .eq("study_program_id", WI_PROGRAM_ID)
        .execute()
    )
    for doc in docs.data or []:
        supabase.table("chunks").delete().eq("document_id", doc["id"]).execute()
        supabase.table("documents").delete().eq("id", doc["id"]).execute()
        print(f"  altes Seed-Dokument entfernt: {doc['id']}")


def main():
    print("Seed: idealtypischer Studienverlauf (WI Bachelor)")
    cleanup_existing()

    doc = (
        supabase.table("documents")
        .insert({
            "filename": FILENAME,
            "study_program_id": WI_PROGRAM_ID,
            "status": "processed",
        })
        .execute()
    )
    document_id = doc.data[0]["id"]
    print(f"  Dokument angelegt: {document_id}")

    chunks = [build_chunk_text(nr, season, courses) for nr, season, courses in SEMESTERS]

    embed = EmbeddingService()
    vectors = embed.embed_texts(chunks)

    for i, ((nr, season, _), content, vector) in enumerate(zip(SEMESTERS, chunks, vectors)):
        supabase.table("chunks").insert({
            "document_id": document_id,
            "content": content,
            "embedding": vector,
            "chunk_index": i,
            "metadata": {
                "source_type": "curriculum_manual",
                "chunk_type": "overview_table",
                "section": "Idealtypischer Studienverlauf (Beginn Wintersemester)",
                "study_program": "Wirtschaftsinformatik",
                "degree": "Bachelor",
                "semester": nr,
                "season": season,
            },
        }).execute()
        print(f"  Chunk {nr}. Semester gespeichert.")

    print(f"Fertig: {len(chunks)} Semester-Chunks eingefuegt.")


if __name__ == "__main__":
    main()
