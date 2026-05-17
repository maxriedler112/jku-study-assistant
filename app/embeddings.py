from __future__ import annotations

from typing import List

MODEL_NAME = "intfloat/multilingual-e5-base"

_cached_model = None


def _get_embedding_model(model_name: str = MODEL_NAME):
    global _cached_model
    if _cached_model is None:
        from sentence_transformers import SentenceTransformer
        _cached_model = SentenceTransformer(model_name)
    return _cached_model


class EmbeddingService:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model = _get_embedding_model(model_name)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        # E5-Modelle brauchen einen kleinen Trick:
        # Man schreibt "passage: " vor den Text für das Indexieren.
        # Das verbessert die Suche enorm!
        prepared_texts = [f"passage: {t}" for t in texts]

        embeddings = self.model.encode(
            prepared_texts,
            normalize_embeddings=True,  # Wichtig für Cosine Similarity in Supabase
            show_progress_bar=True,
        )
        return embeddings.tolist()