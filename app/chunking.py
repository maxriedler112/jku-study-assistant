import re
from typing import List

def clean_text(text: str) -> str:
    if not text:
        return ""

    # A. Silbentrennung entfernen: "Lehrveranstal-\ntung" -> "Lehrveranstaltung"
    # Sucht nach Bindestrich am Zeilenende gefolgt von einem Zeilenumbruch
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # B. Harte Zeilenumbrüche innerhalb von Sätzen fixen
    # Wenn eine Zeile nicht mit einem Satzzeichen endet, gehört die nächste Zeile wahrscheinlich dazu
    lines = text.split('\n')
    cleaned_lines = []
    
    for i in range(len(lines)):
        line = lines[i].strip()
        if not line:
            continue
            
        cleaned_lines.append(line)
        # Wenn die Zeile NICHT mit [. ! ? :] endet, fügen wir ein Leerzeichen statt Umbruch an
        if not re.search(r'[.!?:0-9]$', line): 
            cleaned_lines[-1] += " "
        else:
            cleaned_lines[-1] += "\n" # Echter Absatz

    text = "".join(cleaned_lines)
    
    # C. Mehrfache Leerzeichen säubern
    text = re.sub(r"\s+", " ", text)
    
    return text.strip()

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    # Nutze einen Semantic-Split Ansatz: Trenne primär an Satzenden
    text = clean_text(text)
    
    # Regex-Split an Satzenden, aber behalte das Satzzeichen
    sentences = re.split(r'(?<=[.!?]) +', text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        # Falls ein einzelner Satz schon zu lang ist, hart schneiden (selten)
        if len(sentence) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Harter Schnitt für Überlänge
            for i in range(0, len(sentence), chunk_size - overlap):
                chunks.append(sentence[i:i + chunk_size].strip())
            current_chunk = ""
            continue

        if len(current_chunk) + len(sentence) <= chunk_size:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            # Overlap: Die letzten X Zeichen des alten Chunks mitnehmen
            # Oder besser: Den letzten Satz mitnehmen für den Kontext
            current_chunk = sentence + " "
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks