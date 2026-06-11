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
    'heute', 'morgen', 'uebermorgen',
    'diese woche', 'naechste woche', 'kommende woche',
    'wann', 'termin', 'termine', 'pruefung', 'klausur',
    'ansteht', 'steht an', 'naechster', 'naechste', 'stundenplan',
    'vorlesung', 'lehrveranstaltung',
    'heute', 'morgen', 'übermorgen',
    'diese woche', 'nächste woche', 'kommende woche',
    'prüfung', 'nächster', 'nächste',
]


def is_time_based(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TIME_KEYWORDS)


def get_date_range(question: str):
    q = question.lower()
    today = date.today()

    if 'nächste woche' in q or 'kommende woche' in q or 'naechste woche' in q:
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
        line = f"- {dt}: {ev.get('course_type', '')} {ev['course_name']}"
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
    Erkennt ob eine Frage eine vollstaendige Liste erwartet
    (Kurse, Faecher, LVAs, Semester etc.) statt einer kurzen Erklaerung.
    """
    list_keywords = [
        "welche kurse", "welche fächer", "welche lehrveranstaltungen",
        "welche lvas", "alle kurse", "alle fächer", "liste",
        "auflistung", "überblick", "was gibt es", "steop kurse",
        "pflichtfächer", "wahlfächer", "freifächer",
        "welche vorlesungen", "welche übungen",
        "1. semester", "2. semester", "3. semester",
        "erstes semester", "zweites semester", "drittes semester",
        "pflichtmodule", "grundlagen", "welche module",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in list_keywords)


def _is_full_curriculum_question(question: str) -> bool:
    keywords = [
        "alle fächer", "alle kurse", "alle lehrveranstaltungen",
        "welche fächer hat", "welche kurse hat", "vollständige liste",
        "gesamte studium", "ganzes studium", "komplette liste",
        "was hat das studium", "was umfasst das studium",
    ]
    return any(kw in question.lower() for kw in keywords)


# ── NEU: Erkennung von strukturierten Fragen (Code, Modul, ECTS) ─────────
def _is_structured_question(question: str) -> bool:
    """
    Erkennt Fragen die eine präzise Antwort aus curriculum_row-Chunks
    erwarten: Code-Abfragen, Modul-Zugehörigkeit, ECTS-Werte.
    Diese brauchen mehr Chunks UND Priorisierung von curriculum_row.
    """
    structured_keywords = [
        "welchen code", "welcher code", "code hat",
        "studienfachkennung",
        "gehört zu", "teil von", "zugeordnet",
        "gliedert sich",
        "wie viele ects", "wieviele ects", "ects hat",
        "welche fächer gehören", "welche module gehören",
        "zu welchem fach",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in structured_keywords)


def ask_assistant(question: str, user_id: str = None, study_program_id: str = None) -> str:
    context_parts = []

    # 1. Zeitbasierte Frage → Kalender
    if user_id and _is_valid_user_id(user_id) and is_time_based(question):
        events_text = query_events(question, user_id)
        if events_text:
            context_parts.append(f"KALENDER-EINTRAEGE:\n{events_text}")

    # 2. Match-Count bestimmen je nach Fragetyp
    #    - Listenfragen: 20 (möglichst vollständig)
    #    - Strukturierte Fragen (Code, Modul, ECTS): 15 (genug Curriculum-Chunks)
    #    - Standard: 10 (vorher 6 → war zu wenig)
    if _is_list_question(question) or _is_full_curriculum_question(question):
        match_count = 20
    elif _is_structured_question(question):
        match_count = 15
    else:
        match_count = 10

    # 3. Vektorsuche
    results = search_jku_knowledge(
        question,
        study_program_id=study_program_id,
        match_count=match_count,
    )

    if results:
        # NEU: curriculum_row-Chunks bei ALLEN strukturierten Fragen priorisieren,
        # nicht nur bei Listenfragen. Das stellt sicher dass Code-, ECTS- und
        # Modul-Fragen die richtigen strukturierten Chunks zuerst sehen.
        if _is_list_question(question) or _is_structured_question(question):
            results.sort(key=lambda r: (
                0 if r.get("metadata", {}).get("chunk_type") in ("curriculum_row", "overview_table")
                else 1
            ))
        chunks_text = "\n\n---\n\n".join([res["content"] for res in results])
        context_parts.append(f"CURRICULUM-INFORMATIONEN:\n{chunks_text}")

    # context_parts → fertiger String fuer den System-Prompt
    context_text = (
        "\n\n".join(context_parts)
        if context_parts
        else "Keine relevanten Informationen in der Wissensdatenbank gefunden."
    )

    system_prompt = f"""Du bist ein hilfreicher Studien-Assistent fuer die JKU Linz.
Nutze NUR den unten stehenden Kontext fuer deine Antwort.
Heute ist der {date.today().strftime('%d.%m.%Y')}.

QUELLEN IM KONTEXT:
Der Kontext enthaelt zwei Arten von Quellen:
1. "curriculum_row" / "overview_table": Offizielle Curriculum-Daten (PDF) mit ECTS, Codes und Modulzuordnung.
   Diese Eintraege haben das Format: "Studium: X. Typ: Y. Modul: Z. Code: ABC. Bezeichnung: DEF. ECTS: N."
2. Web-Daten: Detailinfos zu einzelnen Lehrveranstaltungen (Beurteilung, Sprache, Lehrmethode).
Curriculum-Daten haben Vorrang bei ECTS, Codes und Modulzuordnung.
Web-Daten haben Vorrang bei Beurteilungskriterien, Lehrmethoden und Abhaltungssprache.

REGELN:
1. ECTS-Fragen:
   - Nenne den ECTS-Wert des Moduls/Fachs laut Curriculum-Eintrag (z.B. "Datenmodellierung: 6 ECTS").
   - Ignoriere ECTS-Werte einzelner Uebungen oder Vorlesungen aus Web-Daten.
   - Wenn Curriculum und Web-Daten unterschiedliche ECTS zeigen, verwende NUR den Curriculum-Wert.
   - Nenne jeden Wert nur einmal, auch wenn mehrere Quellen ihn bestaetigen.

2. Code-Fragen (Studienfachkennung):
   - Suche im Kontext nach Eintraegen mit "Code: XXX" im Curriculum-Format.
   - Antworte mit dem exakten Code aus dem Curriculum-Eintrag.
   - Beispiel: Wenn im Kontext steht "Code: 526INEN13. Bezeichnung: Information Engineering."
     und die Frage ist "Welchen Code hat Information Engineering?" → Antwort: "526INEN13".

3. Modul-Zugehoerigkeits-Fragen:
   - Suche nach Eintraegen mit "Modul: X" im Curriculum-Format.
   - Liste ALLE Eintraege auf, die diesem Modul zugeordnet sind.
   - Ignoriere Eintraege aus anderen Modulen, auch wenn sie thematisch aehnlich sind.

4. Pflichtfaecher / Wahlfaecher:
   - Liste ALLE im Kontext genannten Pflicht- oder Wahlfaecher auf.
   - Trenne klar zwischen Basiskompetenz und Kernkompetenz.

5. Beurteilung / Lehrmethoden / Sprache:
   - Extrahiere den exakten Wert aus dem Kontext ohne zu umschreiben.
   - Suche gezielt nach "Beurteilungskriterien:", "Lehrmethoden:", "Abhaltungssprache:".

6. Mehrere Quellen mit gleicher Information:
   - Fasse zusammen, liste nicht mehrfach auf.
   - Wenn Curriculum "6 ECTS" sagt und Web-Daten "3 ECTS" fuer eine Teilleistung: nenne nur "6 ECTS".

7. Fehlende Informationen:
   - Wenn die Antwort nicht im Kontext steht: sage klar "Diese Information liegt mir nicht vor."
   - Erfinde KEINE Kurse, ECTS-Werte oder Pruefungsmodalitaeten.

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