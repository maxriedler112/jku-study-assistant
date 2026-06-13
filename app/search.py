import os
from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)


def search_jku_knowledge(query_text: str, study_program_id: str = None, match_count: int = 8):
    """
    Führt eine semantische Vektorsuche (VSS) in der Supabase-Wissensdatenbank durch.
    
    Die Suchanfrage wird vorab expandiert, über den EmbeddingService (E5-Modell) 
    vektorisiert und via RPC-Funktion ('match_documents') mit den gespeicherten 
    Curriculum- und Web-Chunks abgeglichen.
    """
    embed_service = EmbeddingService()

    expanded_query = _expand_query(query_text)

    query_vector = embed_service.model.encode(
        f"query: {expanded_query}",
        normalize_embeddings=True
    ).tolist()

    # 3. Parameter für die PostgreSQL-Ähnlichkeitssuche (Kosinus-Ähnlichkeit) definieren
    params = {
        "query_embedding":   query_vector,
        "match_threshold":   0.3,      
        "match_count":       match_count,  
        "filter_program_id": study_program_id, # Optionaler Filter auf eine bestimmte JKU-Studienrichtung
    }

    # 4. Remote Procedure Call in Supabase triggern und Daten zurückgeben
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
    """
    Reichert die Suchanfrage des Benutzers mit Synonymen, JKU-spezifischen Begriffen 
    und akademischen Ausschreibungen (z. B. 'STEOP', 'LVA') an.
    
    Durch das Anhängen dieser Schlüsselwörter erzielt das dichte Einbettungsmodell 
    (Dense Embedding) eine signifikant höhere Trefferquote bei der Kosinus-Ähnlichkeit 
    auf den strukturierten Curriculum-Daten.
    """
    expansions = {
        # ── JKU Abkürzungen ──────────────────────────────────────────────
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
        "fertigkeiten": "Fertigkeiten Lernergebnisse Learning Outcomes LO",
        "kenntnisse": "Kenntnisse Lernergebnisse Learning Outcomes LO",
        "kompetenzen": "Kompetenzen Lernergebnisse Learning Outcomes LO",
        "lernergebnisse": "Lernergebnisse Kompetenzen Fertigkeiten Kenntnisse Learning Outcomes LO",
    }
    
    result = query
    q_lower = query.lower()
    
    # Iteriere durch das Dictionary und hänge passende Erweiterungen als String-Suffix an
    for term, expanded in expansions.items():
        if term.lower() in q_lower:
            result = result + " " + expanded
            
    return result