import os
from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

# Setup Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

def search_jku_knowledge(query_text: str):
    # 1. Frage in Vektor umwandeln
    # Wichtig: E5-Modelle brauchen bei Fragen das Präfix "query: "
    embed_service = EmbeddingService()
    query_vector = embed_service.model.encode(
        f"query: {query_text}", 
        normalize_embeddings=True
    ).tolist()

    # 2. Die Supabase-Funktion aufrufen
    response = supabase.rpc(
        'match_documents',
        {
            'query_embedding': query_vector,
            'match_threshold': 0.5, # Zeige nur Ergebnisse, die mindestens 50% passen
            'match_count': 3        # Gib die besten 3 Treffer zurück
        }
    ).execute()

    return response.data

if __name__ == "__main__":
    frage = "Wie viele ECTS hat das Bachelorstudium?"
    print(f"Suche nach: {frage}...")
    
    results = search_jku_knowledge(frage)
    
    print("\nErgebnisse aus der Datenbank:")
    for res in results:
        print(f"\n[Ähnlichkeit: {round(res['similarity'] * 100, 2)}%]")
        print(f"Inhalt: {res['content'][:200]}...")