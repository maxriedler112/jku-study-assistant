from __future__ import annotations

from typing import List


def clean_text(text: str) -> str:
    """Bereinigt grob den aus dem PDF extrahierten Text."""
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\t", " ")

    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines = [line for line in lines if line]

    return "\n".join(cleaned_lines).strip()


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Zerlegt Text in überlappende Chunks auf Zeichenbasis.
    """
    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    text = clean_text(text)
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = end - overlap

    return chunks