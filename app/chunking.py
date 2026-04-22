import re
from typing import List

def clean_text(text: str) -> str:
    if not text:
        return ""

    # A. Footer-Zeilen entfernen (Metadaten aus PDF-Fußzeilen, z.B. "Seite 2 von 16")
    text = re.sub(r'GenehmigtvomSenat\S+.*?Inkrafttreten:\S+', '', text)
    text = re.sub(r'Seite\s*\d+\s*von\s*\d+', '', text)

    # B. Silbentrennung entfernen: "Lehrveranstal-\ntung" -> "Lehrveranstaltung"
    # Sucht nach Bindestrich am Zeilenende gefolgt von einem Zeilenumbruch
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # C. Zusammengeklebte Wörter trennen: "Basisund" -> "Basis und"
    # Erkennt Kleinbuchstabe direkt gefolgt von Großbuchstabe ohne Leerzeichen
    text = re.sub(r'([a-zäöüß])([A-ZÄÖÜ])', r'\1 \2', text)

    # D. Harte Zeilenumbrüche innerhalb von Sätzen fixen
    # Wenn eine Zeile nicht mit einem Satzzeichen endet, gehört die nächste Zeile wahrscheinlich dazu
    lines = text.split('\n')
    cleaned_lines = []
    
    for i in range(len(lines)):
        line = lines[i].strip()
        if not line:
            continue
            
        cleaned_lines.append(line)
        # Wenn die Zeile NICHT mit [. ! ? :] endet, fügen wir ein Leerzeichen statt Umbruch an
        if not re.search(r'[.!?:]$', line):
            cleaned_lines[-1] += " "
        else:
            cleaned_lines[-1] += "\n" # Echter Absatz

    text = "".join(cleaned_lines)
    
    # E. Mehrfache Leerzeichen säubern, aber Zeilenumbrüche (Absatzgrenzen) behalten
    text = re.sub(r"[^\S\n]+", " ", text)
    
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
            # Harter Schnitt für Überlänge — an Wortgrenzen
            for i in range(0, len(sentence), chunk_size - overlap):
                end = min(i + chunk_size, len(sentence))
                if end < len(sentence) and sentence[end] != ' ':
                    space_pos = sentence.rfind(' ', i, end)
                    if space_pos > i:
                        end = space_pos
                chunks.append(sentence[i:end].strip())
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