# 🎓 JKU Study Assistant (RAG)

Ein intelligenter Chatbot, der das **JKU Wirtschaftsinformatik Curriculum** "liest" und Fragen dazu präzise beantwortet.
Schluss mit dem mühsamen Durchsuchen von 20-seitigen PDFs!

---

## 🏗️ Funktionsweise (RAG Pipeline)

Das System nutzt eine **Retrieval-Augmented Generation (RAG)** Architektur:

1. **Ingest**
   Das PDF wird extrahiert und in sinnvolle Abschnitte (**Chunks**) unterteilt.

2. **Embed**
   Text wird via `multilingual-e5-base` in hochdimensionale Vektoren umgewandelt.

3. **Store**
   Diese Vektoren werden in einer **Supabase (pgvector)** Datenbank gespeichert.

4. **Chat**
   Bei einer Frage sucht das System die relevantesten Textstellen und lässt
   **Llama 3.1 (Groq)** eine präzise Antwort formulieren.

---

## 🛠️ Tech Stack

* **Sprache:** Python 3.11+
* **KI-Modell:** Llama 3.1 (via Groq API)
* **Embeddings:** `intfloat/multilingual-e5-base`
* **Vektor-DB:** Supabase (PostgreSQL + pgvector)
* **Frontend:** Streamlit

---

## 🚀 Quickstart für Team-Mitglieder

### 1. Setup & Installation

```bash
# 1. Repo klonen & Ordner betreten
git clone <repo-url>
cd jku-study-assistant

# 2. Virtuelle Umgebung erstellen
python -m venv .venv

# 3. venv aktivieren (Windows)
.\.venv\Scripts\Activate.ps1

# 4. Dependencies installieren
pip install -r requirements.txt
```

---

### 2. Environment Variables (.env)

Erstelle eine Datei namens `.env` im Hauptverzeichnis.
**Wichtig:** Diese Datei niemals auf GitHub pushen!

Frag Max nach den aktuellen Keys.

```env
SUPABASE_URL=https://deine-projekt-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=dein-geheimer-key
GROQ_API_KEY=dein-groq-api-key
```

---

### 3. Datenbank-Setup (SQL)

Damit die Suche funktioniert, muss im Supabase SQL Editor einmalig die Suchfunktion angelegt werden.

⚠️ Achte darauf, dass der ID-Typ auf `uuid` eingestellt ist!

---

## ▶️ Verwendung

### Schritt 1: Daten indizieren

Falls die Datenbank noch leer ist oder das PDF aktualisiert wurde:

```bash
python app/ingest.py
python app/upload.py
```

---

### Schritt 2: Den Assistant starten

#### Variante A: Web-Interface (Empfohlen)

```bash
streamlit run app/main.py
beenden mit STRG + C
```

#### Variante B: Terminal (für schnelle Tests)

```bash
python app/assistant.py
```

---

## 📁 Projektstruktur

| Datei              | Beschreibung                              |
| ------------------ | ----------------------------------------- |
| `app/ingest.py`    | PDF-Verarbeitung & Chunking-Logik         |
| `app/upload.py`    | Embeddings erstellen & Upload zu Supabase |
| `app/search.py`    | Vektorsuche (Retrieval-Logik)             |
| `app/assistant.py` | Prompting & Groq-Schnittstelle            |
| `app/main.py`      | Streamlit Frontend                        |

---

## ⚠️ Wichtige Regeln

* 🔐 **Sicherheit:** Die `.env` Datei ist tabu für Git! (.gitignore .env einfügen)
* 🧪 **Umgebung:** Arbeite immer mit aktivierter `.venv`
* 📦 **Versionierung:**
  Wenn du neue Libraries installierst:

```bash
pip freeze > requirements.txt
```

---

## 💡 Tipps

* Wenn Antworten komisch sind → prüfe deine Chunks (Ingest!)
* Wenn nichts gefunden wird → check Embeddings + DB
* Wenn UI spinnt → Streamlit neu starten 😉

---
