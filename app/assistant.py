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
    """
    Validiert, ob die übergebene User-ID entweder eine JKU-Matrikelnummer 
    (z. B. k12345678 oder 1234567) oder eine Standard-UUIDv4 ist.
    """
    if not user_id:
        return False
    user_id = user_id.strip()
    
    # Matrikelnummer: Optionales 'k' gefolgt von 7 bis 8 Ziffern
    if re.match(r'^k?\d{7,8}$', user_id):
        return True
        
    # UUID: Klassisches 8-4-4-4-12 Hexadezimal-Muster
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', user_id):
        return True
    return False


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
    """
    Prüft per Keyword-Matching, ob die Benutzerfrage auf zeitbasierte 
    Informationen (Termine, Stundenplan, Prüfungen) abzielt.
    """
    q = question.lower()
    return any(kw in q for kw in TIME_KEYWORDS)


def get_date_range(question: str):
    """
    Ermittelt basierend auf relativen Zeitangaben in der Frage das passende 
    Start- und Enddatum. Fällt standardmäßig auf ein 28-Tage-Fenster zurück.
    """
    q = question.lower()
    today = date.today()

    # Nächste Woche: Berechne Tage bis zum nächsten Montag, setze Fenster auf Mo-So
    if 'nächste woche' in q or 'kommende woche' in q or 'naechste woche' in q:
        days_until_monday = (7 - today.weekday()) % 7 or 7
        start = today + timedelta(days=days_until_monday)
        end = start + timedelta(days=6)
        
    # Diese Woche: Vom aktuellen Montag bis zum kommenden Sonntag
    elif 'diese woche' in q:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        
    elif 'morgen' in q:
        start = today + timedelta(days=1)
        end = start
        
    elif 'heute' in q:
        start = today
        end = today
        
    # Default-Horizont: Die nächsten 4 Wochen für allgemeine Kalenderanfragen
    else:
        start = today
        end = today + timedelta(days=28)

    return start, end


def query_events(question: str, user_id: str) -> str:
    """
    Sucht KUSSS-Kalendereinträge des Users aus der Supabase-Datenbank, 
    die im berechneten Zeitraum liegen, und formatiert sie als Plain-Text-Liste.
    """
    if not _is_valid_user_id(user_id):
        return ""
    start, end = get_date_range(question)

    # Abfrage der Events innerhalb der Datumsgrenzen (inkl. Puffer für den Endtag)
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

    # String-Formatierung der Events für den LLM-Kontext
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


def query_grades(user_id: str) -> str:
    """
    Lädt die Noten des Users aus completed_courses und formatiert sie
    strukturiert und gruppiert (nach Status und Typ) als Kontext für das LLM.
    """
    if not _is_valid_user_id(user_id):
        return ""

    result = (
        supabase.table("completed_courses")
        .select("course_name,course_type,ects,grade,grade_label,passed,exam_date")
        .eq("user_id", user_id)
        .order("exam_date")
        .execute()
    )

    if not result.data:
        return ""

    total_ects = 0
    passed_count = 0
    failed_count = 0
    grade_sum = 0
    grade_count = 0

    # Dictionaries/Listen für die Gruppierung
    passed_courses_by_type = {}
    failed_courses = []

    for entry in result.data:
        ects = float(entry.get("ects", 0) or 0)
        grade = entry.get("grade")
        passed = entry.get("passed", False)
        label = entry.get("grade_label", "")
        name = entry.get("course_name", "")
        typ = entry.get("course_type", "")
        datum = entry.get("exam_date", "")

        # Einzelne Zeile formatieren
        line = f"- {name}: {ects} ECTS, {label}"
        if datum:
            line += f", {datum}"

        # In entsprechende Gruppe einsortieren
        if passed:
            total_ects += ects
            passed_count += 1
            
            # Gruppieren nach LVA-Typ (VL, UE, KS...)
            if typ not in passed_courses_by_type:
                passed_courses_by_type[typ] = []
            passed_courses_by_type[typ].append(line)
        else:
            failed_count += 1
            line_with_type = f"- {name} ({typ}): {ects} ECTS, {label} [{datum}]"
            failed_courses.append(line_with_type)

        # Schnitt berechnen (nur positive numerische Noten)
        if grade and grade <= 4:
            grade_sum += grade
            grade_count += 1

    schnitt = round(grade_sum / grade_count, 2) if grade_count > 0 else None

    # ---------------------------------------------------------
    # Ausgabe für das LLM zusammenbauen
    # ---------------------------------------------------------
    output_parts = []

    # 1. Zusammenfassung
    summary = [
        "ZUSAMMENFASSUNG:",
        f"Bestanden: {passed_count} | Nicht bestanden: {failed_count}",
        f"Erreichte ECTS: {total_ects}",
    ]
    if schnitt:
        summary.append(f"Notendurchschnitt: {schnitt}")
    output_parts.append("\n".join(summary))

    # 2. Bestandene Kurse nach LVA-Typ sortiert
    if passed_courses_by_type:
        output_parts.append("BESTANDENE LEHRVERANSTALTUNGEN:")
        # Alphabetisch nach LVA-Typ sortieren (z.B. KS, SE, UE, VL)
        for typ, lines in sorted(passed_courses_by_type.items()):
            group_title = f"--- {typ} ---" if typ else "--- Sonstige ---"
            group_text = group_title + "\n" + "\n".join(lines)
            output_parts.append(group_text)

    # 3. Offene / Nicht bestandene Kurse
    if failed_courses:
        output_parts.append("OFFEN / NICHT BESTANDEN:\n" + "\n".join(failed_courses))

    return "\n\n".join(output_parts)


def _is_list_question(question: str) -> bool:
    """
    Prüft, ob der User nach Listen, Semestern oder Modulübersichten sucht, 
    um das Abruflimit (match_count) für Textelemente hochzusetzen.
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
    """
    Erkennt Fragen, die den gesamten Studienplan oder alle Kurse auf einmal 
    abfragen möchten (erfordert maximales Kontext-Fenster).
    """
    keywords = [
        "alle fächer", "alle kurse", "alle lehrveranstaltungen",
        "welche fächer hat", "welche kurse hat", "vollständige liste",
        "gesamte studium", "ganzes studium", "komplette liste",
        "was hat das studium", "was umfasst das studium",
    ]
    return any(kw in question.lower() for kw in keywords)


def _is_structured_question(question: str) -> bool:
    """
    Erkennt gezielte Fragen nach IDs, Studienfachkennungen (Codes), 
    ECTS-Werten oder exakten Modulgliederungen.
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


def _is_grade_question(question: str) -> bool:
    """
    Prüft, ob die Frage persönliche Leistungsdaten, Noten, ECTS-Fortschritt 
    oder offene/fehlende Fächer betrifft.
    """
    grade_keywords = [
        "note", "noten", "benotet", "bestanden", "nicht bestanden",
        "studienerfolg", "notendurchschnitt", "durchschnitt", "schnitt",
        "welche prüfungen", "welche kurse bestanden", "welche lvas bestanden",
        "ects bestanden", "ects geschafft", "ects habe ich",
        "studienfortschritt", "fortschritt",
        "noch offen", "fehlt mir", "was fehlt", "was muss ich noch",
        "meine noten", "meine prüfungen", "meine ects",
        "wie stehe ich", "wie weit bin ich",
        "sehr gut", "genügend", "befriedigend",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in grade_keywords)


def ask_assistant(
    question: str,
    user_id: str = None,
    study_program_id: str = None,
    history: list[dict] = None,
) -> str:
    """
    Zentrale RAG-Pipeline: Analysiert den Fragetyp, füttert den Kontext
    dynamisch aus relationalen DB-Daten (Kalender, Noten) sowie der Vektordatenbank
    (Curriculum-Wissen) und generiert die finale Antwort über Groq (Llama 3.1).

    history: optionale bisherige Konversation als Liste von
    {"role": "user"|"assistant", "content": str}. Wird dem LLM mitgegeben, damit
    Folgefragen ("In welchem Semester wird ES empfohlen?") aufgeloest werden koennen.
    """
    history = history or []

    # Letzte Nutzerfrage aus der Historie ermitteln (verbessert das Retrieval bei
    # Folgefragen, die ohne Kontext mehrdeutig sind).
    last_user_turn = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "user"),
        "",
    )
    search_text = f"{last_user_turn} {question}".strip() if last_user_turn else question

    context_parts = []

    # 1a. Zeitbasierte Frage → Persönliche KUSSS-Termine einspeisen
    if user_id and _is_valid_user_id(user_id) and is_time_based(question):
        events_text = query_events(question, user_id)
        if events_text:
            context_parts.append(f"KALENDER-EINTRAEGE:\n{events_text}")

    # 1b. Noten-Frage → Studienerfolg (Notennachweis) anhängen
    if user_id and _is_valid_user_id(user_id) and _is_grade_question(question):
        grades_text = query_grades(user_id)
        if grades_text:
            context_parts.append(f"DEIN STUDIENERFOLG:\n{grades_text}")

    # 2. Dynamische Steuerung der Ähnlichkeitssuche (Chunk-Menge steuern)
    if _is_list_question(question) or _is_full_curriculum_question(question):
        match_count = 20
    elif _is_structured_question(question):
        match_count = 15
    else:
        match_count = 10

    # 3. Vektorsuche auf Curriculum- und Webdaten ausführen
    #    (search_text enthaelt bei Folgefragen zusaetzlich die vorige Nutzerfrage)
    results = search_jku_knowledge(
        search_text,
        study_program_id=study_program_id,
        match_count=match_count,
    )

    # 4. Suchergebnisse sortieren (Tabellen/Curriculum-Zeilen vor unstrukturierten Web-Daten ranken)
    if results:
        if _is_list_question(question) or _is_structured_question(question):
            results.sort(key=lambda r: (
                0 if r.get("metadata", {}).get("chunk_type") in ("curriculum_row", "overview_table")
                else 1
            ))
        chunks_text = "\n\n---\n\n".join([res["content"] for res in results])
        context_parts.append(f"CURRICULUM-INFORMATIONEN:\n{chunks_text}")

    # Name des aktuell gewaehlten Studiengangs (fuer Systemgrenzen-Hinweise im Prompt)
    selected_program = None
    if results:
        selected_program = results[0].get("metadata", {}).get("study_program")
    program_hint = (
        f'Der Nutzer hat aktuell den Studiengang "{selected_program}" ausgewaehlt. '
        f"Du beantwortest ausschliesslich Fragen zu diesem Studiengang."
        if selected_program
        else "Der Nutzer hat einen Studiengang ueber den Filter ausgewaehlt."
    )

    # Kontext final zusammenbauen oder Fallback definieren
    context_text = (
        "\n\n".join(context_parts)
        if context_parts
        else "Keine relevanten Informationen in der Wissensdatenbank gefunden."
    )

    # Strict System Prompt zur Einhaltung der JKU-Datenhierarchie definieren
    system_prompt = f"""Du bist ein hilfreicher Studien-Assistent fuer die JKU Linz.
Nutze NUR den unten stehenden Kontext fuer deine Antwort.
Heute ist der {date.today().strftime('%d.%m.%Y')}.
{program_hint}

QUELLEN IM KONTEXT:
Der Kontext enthaelt bis zu drei Arten von Quellen:
1. "curriculum_row" / "overview_table": Offizielle Curriculum-Daten (PDF) mit ECTS, Codes und Modulzuordnung.
   Diese Eintraege haben das Format: "Studium: X. Typ: Y. Modul: Z. Code: ABC. Bezeichnung: DEF. ECTS: N."
2. Web-Daten: Detailinfos zu einzelnen Lehrveranstaltungen (Beurteilung, Sprache, Lehrmethode).
3. "DEIN STUDIENERFOLG": Persoenliche Noten und ECTS des aktuellen Users.
Curriculum-Daten haben Vorrang bei ECTS und Modulzuordnung.
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

7. Fehlende Informationen & Systemgrenzen:
   - Erfinde NIEMALS Kurse, ECTS-Werte oder Pruefungsmodalitaeten.
   - Wenn die Frage zum gewaehlten Studiengang passt, aber die Antwort nicht im Kontext steht:
     sage freundlich, dass dir diese konkrete Information nicht vorliegt, und empfiehl,
     im offiziellen Curriculum, im Studienhandbuch oder in KUSSS nachzusehen.
   - Wenn sich die Frage auf einen ANDEREN Studiengang bezieht (z.B. Medizin, Jus):
     erklaere, dass du nur Fragen zum aktuell ueber den Filter gewaehlten Studiengang
     beantworten kannst, und schlage vor, oben den passenden Studiengang auszuwaehlen
     (falls verfuegbar).
   - Wenn die Frage gar nichts mit dem Studium zu tun hat (z.B. Mensa-Menue, Wetter,
     Parkplaetze): weise freundlich darauf hin, dass du ein Studien-Assistent bist und
     nur bei Fragen rund um Curriculum, Lehrveranstaltungen und Studienfortschritt helfen
     kannst. Rate NICHT und erfinde keine Antwort.

8. Noten- und Fortschrittsfragen:
   - Nutze AUSSCHLIESSLICH die Daten unter "DEIN STUDIENERFOLG" fuer persoenliche Fragen.
   - Liste NUR Eintraege auf, die EXAKT so im Kontext stehen. Erfinde KEINE zusaetzlichen Eintraege.
   - Bei Fragen nach Noten eines bestimmten Kurses: suche alle Eintraege die den gefragten Kursnamen enthalten. Liste nur diese auf, keine anderen Kurse.
   - Bei "wie viele ECTS": nenne die ECTS-Summe aus der ZUSAMMENFASSUNG, nicht selbst zaehlen.
   - Bei "Notendurchschnitt": nenne den Wert aus der ZUSAMMENFASSUNG.
   - Bei "was fehlt mir noch": Das Bachelorstudium Wirtschaftsinformatik umfasst 180 ECTS.
     Rechne: 180 minus bestandene ECTS = fehlende ECTS. Nenne NUR diese Zahl.
     Liste KEINE konkreten fehlenden Kurse auf, da du nicht sicher weisst welche das sind.
     Empfehle stattdessen, den Studienfortschritt in KUSSS zu pruefen.

9. Ton & Formulierung:
   - Antworte freundlich, klar und in vollstaendigen deutschen Saetzen.
   - Bleibe praezise und fasse dich kurz; keine internen Hinweise wie "laut Kontext"
     oder "im Kontext steht". Formuliere die Antwort direkt fuer die studierende Person.

KONTEXT:
{context_text}
"""

    # 5. Nachrichten zusammenbauen: System-Prompt + bisherige Historie + aktuelle Frage.
    #    Nur die letzten Turns mitschicken, um das Token-Budget zu schonen.
    recent_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages = (
        [{"role": "system", "content": system_prompt}]
        + recent_history
        + [{"role": "user", "content": question}]
    )

    # 6. API-Inferenz über Groq ausführen
    chat_completion = client.chat.completions.create(
        messages=messages,
        model="llama-3.1-8b-instant",
        temperature=0.2, # Niedrige Temperatur für geringe Halluzinationsanfälligkeit
    )

    return chat_completion.choices[0].message.content


if __name__ == "__main__":
    user_frage = input("Deine Frage: ")
    antwort = ask_assistant(user_frage)
    print("\n" + "=" * 50)
    print(antwort)
    print("=" * 50)