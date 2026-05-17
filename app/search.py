import os
import re
from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)


def search_jku_knowledge(query_text: str, study_program_id: str = None, match_count: int = 8):
    embed_service = EmbeddingService()
    
    # Query Expansion: Bekannte Abkürzungen ausschreiben
    # → besseres semantisches Matching
    expanded_query = _expand_query(query_text)
    
    query_vector = embed_service.model.encode(
        f"query: {expanded_query}",
        normalize_embeddings=True
    ).tolist()

    params = {
        "query_embedding":   query_vector,
        "match_threshold":   0.3,      
        "match_count":       match_count,  
        "filter_program_id": study_program_id,
    }

    response = supabase.rpc("match_documents", params).execute()
    return response.data or []


def _expand_query(query: str) -> str:
    """
    Erweitert bekannte JKU-Abkürzungen im Query-Text.
    Das verbessert das semantische Matching erheblich, weil
    das Embedding-Modell den ausgeschriebenen Begriff besser
    mit dem Curriculum-Text verknüpfen kann.
    """
    expansions = {
        "STEOP": "Studieneingangs- und Orientierungsphase STEOP",
        "ECTS":  "ECTS Leistungspunkte Credits",
        "VL":    "Vorlesung VL",
        "UE":    "Übung UE",
        "KV":    "Kombinierte Lehrveranstaltung KV",
        "SE":    "Seminar SE",
        "PR":    "Praktikum PR",
        "LVA":   "Lehrveranstaltung LVA",
        "StEOP": "Studieneingangs- und Orientierungsphase StEOP",
        "beurteilung":    "Beurteilungskriterien Pruefung Abschlussklausur",
        "benotet":        "Beurteilungskriterien Note",
        "pruefung":       "Beurteilungskriterien Pruefungsmodalitaeten",
        "wie wird":       "Beurteilungskriterien",
        "lehrmethode":    "Lehrmethoden Vortrag Uebung",
        "sprache":        "Abhaltungssprache Deutsch Englisch",
        "voraussetzung":  "Anmeldevoraussetzungen",
        "teilungsziffer": "Teilungsziffer Zuteilungsverfahren",
    }
    result = query
    for term, expanded in expansions.items():
        if term in result.lower():
            result = result + " " + expanded
    return result
