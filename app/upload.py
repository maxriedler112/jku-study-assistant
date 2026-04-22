import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise ValueError("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt in der .env Datei")

supabase: Client = create_client(url, key)


def upload_data(file_path: str = "data/chunks_with_embeddings.json"):
    if not os.path.exists(file_path):
        print(f"Fehler: '{file_path}' wurde nicht gefunden!")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Starte Upload von {len(data)} Chunks...")

    success = 0
    errors  = 0
    for chunk in data:
        row = {
            "content":     chunk["content"],
            "embedding":   chunk["embedding"],
            "metadata":    chunk["metadata"],
            "chunk_index": chunk["metadata"].get("chunk_index"),
        }
        try:
            supabase.table("chunks").insert(row).execute()
            success += 1
        except Exception as e:
            print(f"  Fehler bei Chunk {chunk['metadata'].get('chunk_index')}: {e}")
            errors += 1

    print(f"✅ {success} Chunks hochgeladen, {errors} Fehler.")


if __name__ == "__main__":
    upload_data()
