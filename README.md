🎓 JKU Study Assistant (RAG)
Ein intelligenter Chatbot, der das JKU Wirtschaftsinformatik Curriculum "liest" und Fragen dazu präzise beantwortet.

🏗️ Funktionsweise (RAG Pipeline)
Ingest: PDF wird in kleine Stücke (Chunks) geschnitten.

Embed: Text wird in Vektoren umgewandelt (E5-Multilingual Model).

Store: Vektoren landen in der Supabase (pgvector) Datenbank.

Chat: User fragt → Datenbank sucht Kontext → Llama 3 (Groq) antwortet.

🛠️ Tech Stack
Sprache: Python 3.11+

KI-Modell: Llama 3.1 (via Groq API)

Embeddings: intfloat/multilingual-e5-base

Vektor-DB: Supabase (PostgreSQL)

Frontend: Streamlit

🚀 Quickstart (für Team-Mitglieder)
1. Setup & Installation
Bash
# Repo klonen & Ordner betreten
git clone <repo-url>
cd jku-study-assistant

# venv erstellen & aktivieren (Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Dependencies installieren
pip install -r requirements.txt
2. Environment Variables (.env)
Erstelle eine Datei namens .env im Hauptverzeichnis. Frage Alex nach den Keys!

Code-Snippet
SUPABASE_URL=https://deine-url.supabase.co
SUPABASE_SERVICE_ROLE_KEY=dein-geheimer-key
GROQ_API_KEY=dein-groq-api-key
3. Datenbank-Funktion (Einmalig)
Damit die Suche funktioniert, muss in der Supabase SQL-Konsole die Funktion match_documents angelegt sein (Code findest du in scripts/setup.sql oder frag Alex).

▶️ Bedienung
Schritt 1: Daten indizieren (optional, falls DB leer)
Liest das PDF ein und lädt es hoch:

Bash
python app/ingest.py
python app/upload.py
Schritt 2: Den Assistant starten
Variante A: Terminal (für Tests)

Bash
python app/assistant.py
Variante B: Web-Interface (empfohlen)

Bash
streamlit run app/main.py
📁 Projektstruktur
app/ingest.py: PDF-Processing & Chunking.

app/upload.py: Upload der Vektoren zu Supabase.

app/search.py: Die Logik hinter der Vektorsuche.

app/assistant.py: Verbindung zur Groq-KI.

app/main.py: Das Streamlit Frontend.

⚠️ Wichtige Regeln
NIEMALS die .env Datei committen (ist in .gitignore).

venv muss immer aktiv sein beim Starten.
