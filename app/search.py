import os
import re
from dotenv import load_dotenv
from supabase import create_client, Client
from app.embeddings import EmbeddingService

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

STUDY_PROGRAM_UUID_MAP = {
    "bachelor": "9d71571c-b521-44a4-b40a-f4041112e6c3",
    "master": "cdf7769e-4c01-4945-bc9f-937861829643",
}

UUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)


def normalize_study_program_id(study_program_id: str | None) -> str | None:
    if not study_program_id:
        return None

    study_program_id = study_program_id.strip()
    if UUID_PATTERN.match(study_program_id):
        return study_program_id

    mapped_id = STUDY_PROGRAM_UUID_MAP.get(study_program_id.lower())
    if mapped_id:
        return mapped_id

    print(f"search_jku_knowledge: ignored invalid study_program_id={study_program_id}")
    return None


def search_jku_knowledge(query_text: str, study_program_id: str = None):
    embed_service = EmbeddingService()
    query_vector = embed_service.model.encode(
        f"query: {query_text}",
        normalize_embeddings=True
    ).tolist()

    study_program_id = normalize_study_program_id(study_program_id)
    params = {
        "query_embedding":   query_vector,
        "match_threshold":   0.5,
        "match_count":       3,
        "filter_program_id": study_program_id,
    }

    response = supabase.rpc("match_documents", params).execute()
    return response.data or []
