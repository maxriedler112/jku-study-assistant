🎓 JKU Study Assistant (RAG)
Ein intelligenter Chatbot, der das JKU Wirtschaftsinformatik Curriculum "liest" und Fragen dazu präzise beantwortet. Schluss mit dem mühsamen Durchsuchen von 20-seitigen PDFs!

🏗️ Funktionsweise (RAG Pipeline)
Das System nutzt eine Retrieval-Augmented Generation (RAG) Architektur:

Ingest: Das PDF wird extrahiert und in sinnvolle Abschnitte (Chunks) unterteilt.

Embed: Text wird via multilingual-e5-base in hochdimensionale Vektoren umgewandelt.

Store: Diese Vektoren werden in einer Supabase (pgvector) Datenbank gespeichert.

Chat: Bei einer Frage sucht das System die relevantesten Textstellen und lässt Llama 3.1 (Groq) eine präzise Antwort formulieren.

🛠️ Tech Stack
Sprache: Python 3.11+

KI-Modell: Llama 3.1 (via Groq API)

Embeddings: intfloat/multilingual-e5-base

Vektor-DB: Supabase (PostgreSQL + pgvector)

Frontend: Streamlit

🚀 Quickstart für Team-Mitglieder
1. Setup & Installation
Bash
# 1. Repo klonen & Ordner betreten
git clone <repo-url>
cd jku-study-assistant

# 2. Virtuelle Umgebung erstellen
python -m venv .venv

# 3. venv aktivieren (Windows)
.\.venv\Scripts\Activate.ps1

# 4. Dependencies installieren
pip install -r requirements.txt
2. Environment Variables (.env)
Erstelle eine Datei namens .env im Hauptverzeichnis. Wichtig: Diese Datei niemals auf GitHub pushen! Frag Alex nach den aktuellen Keys.

Code-Snippet
SUPABASE_URL=https://deine-projekt-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=dein-geheimer-key
GROQ_API_KEY=dein-groq-api-key
3. Datenbank-Setup (SQL)
Damit die Suche funktioniert, muss im Supabase SQL Editor einmalig die Suchfunktion angelegt werden. Den Code findest du in scripts/setup.sql. (Achte darauf, dass der ID-Typ auf uuid eingestellt ist!)

▶️ Bedienung
Schritt 1: Daten indizieren
Falls die Datenbank noch leer ist oder das PDF aktualisiert wurde:

Bash
python app/ingest.py
python app/upload.py
Schritt 2: Den Assistant starten
Wir empfehlen das Web-Interface für die beste User Experience:

Variante A: Web-Interface (Empfohlen)

Bash
streamlit run app/main.py
Variante B: Terminal (Nur für schnelle Tests)

Bash
python app/assistant.py
📁 Projektstruktur
Datei	Beschreibung
app/ingest.py	PDF-Verarbeitung & Chunking-Logik
app/upload.py	Erstellung der Embeddings & Upload zu Supabase
app/search.py	Kern-Logik der Vektorsuche (Retrieval)
app/assistant.py	Prompt-Engineering & Groq-Schnittstelle
app/main.py	Streamlit Frontend (UI)
⚠️ Wichtige Regeln
Sicherheit: Die .env Datei ist tabu für Git!

Umgebung: Arbeite immer mit aktivierter (.venv).

Versionierung: Wenn du neue Libraries installierst, aktualisiere die requirements.txt mit pip freeze > requirements.txt.
