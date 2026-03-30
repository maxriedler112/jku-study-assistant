# 🧠 JKU Study Assistant (RAG)

## 🎯 Projektziel

Ziel dieses Projekts ist die Entwicklung eines Chatbots für JKU-Studierende, der Fragen zu:

* Studienrichtungen
* Curriculum
* Kursen

beantworten kann.

👉 Aktueller Fokus: **WIN Curriculum (PDF)**

---

## 💡 Konzept (RAG)

Das System basiert auf **Retrieval-Augmented Generation (RAG)**:

1. User stellt eine Frage in natürlicher Sprache
2. System sucht relevante Inhalte im Curriculum
3. LLM generiert eine Antwort basierend auf diesen Daten

👉 Vorteil: weniger Halluzinationen, Antworten basieren auf echten Dokumenten

---

## ⚙️ Tech Stack

* **Backend:** Python (FastAPI – geplant)
* **RAG Pipeline:**
  PDF → Text → Chunks → Embeddings → Retrieval → LLM
* **Datenbank:** Supabase (PostgreSQL + pgvector)
* **Frontend:** Angular oder React (später)

---

## 📁 Projektstruktur

```
jku-study-assistant/
│
├── app/
│   ├── ingest.py        # Hauptpipeline (PDF → Embeddings)
│   ├── chunking.py      # Text-Chunking
│   └── embeddings.py    # Embedding-Generierung
│
├── data/
│   └── curriculum.pdf   # Input-Dokument
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🚀 Setup

### 1. Projekt klonen

```bash
git clone <repo-url>
cd jku-study-assistant
```

### 2. Virtuelle Umgebung erstellen

```bash
python -m venv .venv
```

### 3. venv aktivieren (Windows / PowerShell)

```bash
.venv\Scripts\Activate.ps1
```

Falls Fehler:

```bash
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### 4. Dependencies installieren

```bash
pip install -r requirements.txt
```

---

## ▶️ Nutzung (Ingestion Pipeline)

PDF einlesen + Chunking + Embeddings:

```bash
python app/ingest.py
```

---

## 📦 Output

Nach erfolgreichem Run:

```
data/chunks_with_embeddings.json
```

Enthält:

* Text-Chunks
* Metadaten (Seite, Index)
* Embeddings (Vektoren)

---

## 🧪 Aktueller Stand

✅ PDF-Extraktion funktioniert
✅ Chunking implementiert
✅ Embeddings generiert
⬜ Supabase Integration
⬜ Retrieval / Search
⬜ Chatbot

---

## ⚠️ Wichtige Hinweise für Team

### 1. Immer venv aktivieren

Vor jedem Run:

```bash
.venv\Scripts\Activate.ps1
```

---

### 2. Nicht committen

Diese Dinge dürfen NICHT gepusht werden:

* `.venv/`
* große generierte Dateien (z. B. JSON mit Embeddings)
* `.env` Dateien

---

### 3. Python-Version

Empfohlen:

* Python **3.11 oder 3.12**

Aktuell:

* 3.14 kann funktionieren, aber evtl. Probleme bei Libraries

---

### 4. Pfade beachten

* PDF muss in `data/` liegen
* Dateiname muss mit `ingest.py` übereinstimmen

---

### 5. Erste Fehlersuche

Wenn etwas nicht funktioniert:

* venv aktiv?
* richtige Ordnerstruktur?
* `pip install` ausgeführt?
* Fehlermeldung genau lesen

---

## 🔜 Nächste Schritte

* Supabase + pgvector Integration
* Similarity Search
* FastAPI Endpoint
* Chat Interface

---

## 💬 Ziel

Ein funktionierender Studien-Chatbot, der auf echten JKU-Daten basiert.

---
