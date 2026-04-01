import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client

# 1. Verbindung zur .env Datei herstellen
load_dotenv()

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# 2. Supabase Client starten
supabase: Client = create_client(URL, KEY)

def upload_data():
    # Pfad zu deinen berechneten Chunks
    file_path = "data/chunks_with_embeddings.json"
    
    if not os.path.exists(file_path):
        print("Fehler: Die Datei 'chunks_with_embeddings.json' wurde nicht gefunden!")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Starte Upload von {len(data)} Chunks...")

    # Wir laden die Daten hoch
    for chunk in data:
        # Wir passen die Struktur an deine Supabase-Tabelle an
        row = {
            "content": chunk["content"],
            "embedding": chunk["embedding"],
            "metadata": chunk["metadata"]
        }
        
        try:
            supabase.table("documents").insert(row).execute()
        except Exception as e:
            print(f"Fehler beim Hochladen eines Chunks: {e}")
            break

    print("✅ Alle Daten wurden erfolgreich zu Supabase hochgeladen!")

if __name__ == "__main__":
    upload_data()