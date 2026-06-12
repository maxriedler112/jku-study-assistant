import os
from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)


def search_jku_knowledge(query_text: str, study_program_id: str = None, match_count: int = 8):
    embed_service = EmbeddingService()

    expanded_query = _expand_query(query_text)

    query_vector = embed_service.model.encode(
        f"query: {expanded_query}",
        normalize_embeddings=True
    ).tolist()

    params = {
        "query_embedding": query_vector,
        "match_threshold": 0.3,
        "match_count": match_count,
        "filter_program_id": study_program_id,
    }

    response = supabase.rpc("match_documents", params).execute()
    results = response.data or []

    print("\nTOP RESULTS")
    for r in results:
        metadata = r.get("metadata", {})

        print(
            metadata.get("lva_name"),
            "|",
            metadata.get("section"),
            "|",
            metadata.get("subsection"),
            "| similarity:",
            r.get("similarity")
        )

    return results


def _expand_query(query: str) -> str:
    expansions = {
        "STEOP": "Studieneingangs- und Orientierungsphase STEOP",
        "ECTS": "ECTS Leistungspunkte Credits",
        "VL": "Vorlesung VL",
        "UE": "Übung UE",
        "KV": "Kombinierte Lehrveranstaltung KV",
        "SE": "Seminar SE",
        "PR": "Praktikum PR",
        "LVA": "Lehrveranstaltung LVA",
        "StEOP": "Studieneingangs- und Orientierungsphase StEOP",
        "beurteilung": "Beurteilungskriterien Pruefung Abschlussklausur",
        "benotet": "Beurteilungskriterien Note",
        "pruefung": "Beurteilungskriterien Pruefungsmodalitaeten",
        "wie wird": "Beurteilungskriterien",
        "lehrmethode": "Lehrmethoden Vortrag Uebung",
        "sprache": "Abhaltungssprache Deutsch Englisch",
        "voraussetzung": "Anmeldevoraussetzungen",
        "teilungsziffer": "Teilungsziffer Zuteilungsverfahren",
        "fertigkeiten": "Fertigkeiten Lernergebnisse Learning Outcomes LO",
        "kenntnisse": "Kenntnisse Lernergebnisse Learning Outcomes LO",
        "kompetenzen": "Kompetenzen Lernergebnisse Learning Outcomes LO",
        "lernergebnisse": "Lernergebnisse Kompetenzen Fertigkeiten Kenntnisse Learning Outcomes LO",
    }

    result = query

    for term, expanded in expansions.items():
        if term.lower() in result.lower():
            result = result + " " + expanded

    return result