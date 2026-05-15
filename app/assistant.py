import os
import re
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client, Client
from search import search_jku_knowledge

load_dotenv()

_groq_key = os.getenv("GROQ_API_KEY")
_url       = os.getenv("SUPABASE_URL")
_key       = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not _groq_key:
    raise ValueError("GROQ_API_KEY fehlt in der .env Datei")
if not _url or not _key:
    raise ValueError("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt in der .env Datei")

client   = Groq(api_key=_groq_key)
supabase: Client = create_client(_url, _key)


def _is_valid_user_id(user_id: str) -> bool:
    """JKU Matrikelnummer: optionales 'k' + 7-8 Ziffern."""
    return bool(user_id and re.match(r'^k?\d{7,8}$', user_id.strip()))

TIME_KEYWORDS = [
    'heute', 'morgen', 'übermorgen',
    'diese woche', 'nächste woche', 'kommende woche',
    'wann', 'termin', 'termine', 'prüfung', 'klausur',
    'ansteht', 'steht an', 'nächster', 'nächste', 'stundenplan',
    'vorlesung', 'lehrveranstaltung',
]

def is_time_based(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TIME_KEYWORDS)


def get_date_range(question: str):
    q = question.lower()
    today = date.today()

    if 'nächste woche' in q or 'kommende woche' in q:
        days_until_monday = (7 - today.weekday()) % 7 or 7
        start = today + timedelta(days=days_until_monday)
        end = start + timedelta(days=6)
    elif 'diese woche' in q:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif 'morgen' in q:
        start = today + timedelta(days=1)
        end = start
    elif 'heute' in q:
        start = today
        end = today
    else:
        # Allgemeine Termin-Frage: nächste 4 Wochen
        start = today
        end = today + timedelta(days=28)

    return start, end


def query_events(question: str, user_id: str) -> str:
    if not _is_valid_user_id(user_id):
        return ""
    start, end = get_date_range(question)

    response = (
        supabase.table("events")
        .select("course_name,course_type,event_type,description,start_dt,end_dt,location")
        .eq("user_id", user_id)
        .gte("start_dt", start.isoformat())
        .lte("start_dt", (end + timedelta(days=1)).isoformat())
        .order("start_dt")
        .execute()
    )

    if not response.data:
        return ""

    lines = []
    for ev in response.data:
        dt = datetime.fromisoformat(ev["start_dt"]).strftime("%d.%m.%Y %H:%M")
        line = f"- {dt}: {ev.get('course_type','')} {ev['course_name']}"
        if ev.get("event_type"):
            line += f" [{ev['event_type']}]"
        if ev.get("location"):
            line += f" | Raum: {ev['location']}"
        if ev.get("description"):
            line += f" | {ev['description']}"
        lines.append(line)

    return "\n".join(lines)


def _is_list_question(question: str) -> bool:
    """
    Erkennt ob eine Frage eine vollständige Liste erwartet
    (Kurse, Fächer, LVAs, etc.) statt einer kurzen Erklärung.
    """
    list_keywords = [
        "welche kurse", "welche fächer", "welche lehrveranstaltungen",
        "welche lvas", "alle kurse", "alle fächer", "liste",
        "auflistung", "überblick", "was gibt es", "steop kurse",
        "pflichtfächer", "wahlfächer", "freifächer",
        "welche vorlesungen", "welche übungen",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in list_keywords)


def ask_assistant(question: str, user_id: str = None, study_program_id: str = None) -> str:
    context_parts = []

    # Zeitbasierte Frage → Kalender
    if user_id and _is_valid_user_id(user_id) and is_time_based(question):
        events_text = query_events(question, user_id)
        if events_text:
            context_parts.append(f"KALENDER-EINTRÄGE:\n{events_text}")

    # Listenfragen brauchen mehr Chunks
    match_count = 12 if _is_list_question(question) else 6

    results = search_jku_knowledge(
        question,
        study_program_id=study_program_id,
        match_count=match_count,
    )

    if results:
        # Tabellen-Chunks zuerst sortieren bei Listenfragen
        if _is_list_question(question):
            results.sort(key=lambda r: (
                0 if "|" in r.get("content", "") else 1  # Tabellen vorne
            ))
        chunks_text = "\n\n---\n\n".join([res["content"] for res in results])
        context_parts.append(f"CURRICULUM-INFORMATIONEN:\n{chunks_text}")

    system_prompt = f"""Du bist ein hilfreicher Studien-Assistent für die JKU.
Nutze NUR den unten stehenden Kontext für deine Antwort.

WICHTIGE REGELN:
- Bei Fragen nach Kursen, Fächern oder Lehrveranstaltungen: 
  Liste ALLE im Kontext genannten auf, nicht nur die ersten.
- Wenn Tabellen im Kontext stehen: übertrage sie vollständig als Liste.
- Antworte auf Deutsch. Heute: {date.today().strftime('%d.%m.%Y')}.
- Wenn Informationen fehlen: sage es ehrlich.
- Erfinde KEINE Kurse oder ECTS-Punkte.

KONTEXT:
{context_text}
"""

    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        model="llama-3.1-8b-instant",
        temperature=0.2,
    )

    return chat_completion.choices[0].message.content


if __name__ == "__main__":
    user_frage = input("Deine Frage: ")
    antwort = ask_assistant(user_frage)
    print("\n" + "=" * 50)
    print(antwort)
    print("=" * 50)
