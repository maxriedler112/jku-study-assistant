import os
from dotenv import load_dotenv
from supabase import create_client, Client
from embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)


def search_jku_knowledge(query_text: str, study_program_id: str = None):
    embed_service = EmbeddingService()
    query_vector = embed_service.model.encode(
        f"query: {query_text}",
        normalize_embeddings=True
    ).tolist()

    params = {
        "query_embedding":   query_vector,
        "match_threshold":   0.5,
        "match_count":       3,
        "filter_program_id": study_program_id,  # None = alle Studiengänge durchsuchen
    }

    response = supabase.rpc("match_documents", params).execute()
    return response.data or []
