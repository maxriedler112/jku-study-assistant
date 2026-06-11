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
    Erweitert bekannte JKU-Abkürzungen und Fragetypen im Query-Text.
    Das verbessert das semantische Matching erheblich, weil
    das Embedding-Modell den ausgeschriebenen Begriff besser
    mit dem Curriculum-Text verknüpfen kann.
    
    ÄNDERUNGEN V2:
    - NEU: Expansions für Code/Studienfachkennung-Abfragen
    - NEU: Expansions für Modul-Zugehörigkeits-Fragen
    - NEU: Expansions für Semester-/Studienverlauf-Fragen
    """
    expansions = {
        # ── Abkürzungen ──────────────────────────────────────────────
        "STEOP":  "Studieneingangs- und Orientierungsphase STEOP",
        "ECTS":   "ECTS Leistungspunkte Credits",
        "VL":     "Vorlesung VL",
        "UE":     "Übung UE",
        "KV":     "Kombinierte Lehrveranstaltung KV",
        "SE":     "Seminar SE",
        "PR":     "Praktikum PR",
        "LVA":    "Lehrveranstaltung LVA",
        "StEOP":  "Studieneingangs- und Orientierungsphase StEOP",
        
        # ── Code / Studienfachkennung ────────────────────────────────
        "code":              "Code Studienfachkennung Kennzahl",
        "studienfachkennung": "Code Studienfachkennung",
        "kennzahl":          "Code Studienfachkennung Kennzahl",
        
        # ── Modul-Zugehörigkeit ──────────────────────────────────────
        "gehört zu":         "Modul Fach gliedert sich Zuordnung",
        "teil von":          "Modul Fach gliedert sich Zuordnung",
        "welche module":     "Modul gliedert sich Module Fächer",
        "welche fächer":     "Modul Fach Pflichtfächer Wahlfächer gliedert",
        "gliedert":          "Modul Fach gliedert Module",
        
        # ── Semester / Studienverlauf ────────────────────────────────
        "semester":          "Semester idealtypischer Studienverlauf",
        "studienverlauf":    "idealtypischer Studienverlauf Semester",
        "studienplan":       "idealtypischer Studienverlauf Studienplan Semester",
        
        # ── Beurteilung / Lehrmethoden ───────────────────────────────
        "beurteilung":       "Beurteilungskriterien Pruefung Abschlussklausur",
        "benotet":           "Beurteilungskriterien Note",
        "pruefung":          "Beurteilungskriterien Pruefungsmodalitaeten",
        "prüfungsordnung":   "Prüfungsordnung Prüfungsregelungen Fachprüfungen Studienhandbuch",
        "wie wird":          "Beurteilungskriterien",
        "lehrmethode":       "Lehrmethoden Vortrag Uebung",
        "sprache":           "Abhaltungssprache Deutsch Englisch",
        "voraussetzung":     "Anmeldevoraussetzungen",
        "teilungsziffer":    "Teilungsziffer Zuteilungsverfahren",
    }
    result = query
    q_lower = query.lower()
    for term, expanded in expansions.items():
        if term.lower() in q_lower:
            result = result + " " + expanded
    return result