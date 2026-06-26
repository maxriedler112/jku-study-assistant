import os
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from groq import Groq, APIStatusError
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

    # Abfrage der Events innerhalb der Datumsgrenzen (inkl. Puffer für den Endtag).
    # events.user_id ist vom Typ uuid; bei Matrikelnummern (oder anderen Mismatches)
    # wirft Postgres einen Fehler -> defensiv abfangen statt die Anfrage zu killen.
    try:
        response = (
            supabase.table("events")
            .select("course_name,course_type,event_type,description,start_dt,end_dt,location")
            .eq("user_id", user_id)
            .gte("start_dt", start.isoformat())
            .lte("start_dt", (end + timedelta(days=1)).isoformat())
            .order("start_dt")
            .execute()
        )
    except Exception as exc:
        print(f"query_events: uebersprungen ({exc})")
        return ""

    if not response.data:
        return ""

    # String-Formatierung der Events für den LLM-Kontext.
    # start_dt kommt als UTC -> nach Europe/Vienna umrechnen (sonst 1-2h Versatz).
    lines = []
    for ev in response.data:
        dt = (
            datetime.fromisoformat(ev["start_dt"])
            .astimezone(ZoneInfo("Europe/Vienna"))
            .strftime("%d.%m.%Y %H:%M")
        )
        course_type = ev.get("course_type") or ""
        line = f"- {dt}: {course_type} {ev['course_name']}".replace("  ", " ")
        if ev.get("event_type"):
            line += f" [{ev['event_type']}]"
        if ev.get("location"):
            line += f" | Raum: {ev['location']}"
        if ev.get("description"):
            line += f" | {ev['description']}"
        lines.append(line)

    return "\n".join(lines)


def _user_has_any_events(user_id: str) -> bool:
    """
    Prueft, ob fuer den Nutzer ueberhaupt Kalender-Events gespeichert sind.

    Wichtig, um "kein Kalender hochgeladen" von "Kalender vorhanden, aber im
    erfragten Zeitraum keine Termine" zu unterscheiden. Sonst meldet der Assistent
    faelschlich, es sei kein Kalender hinterlegt (siehe Eval #14 "Was steht morgen an?").
    """
    if not _is_valid_user_id(user_id):
        return False
    try:
        resp = (
            supabase.table("events")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception as exc:
        print(f"_user_has_any_events: uebersprungen ({exc})")
        return False


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
        "wie viele ects", "wieviele ects", "wieviel ects", "wie viel ects",
        "ects hat", "ects bekomme", "ects bekommt", "ects gibt",
        "ects für", "ects fuer", "ects bringt", "ects sind",
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
        # ECTS-/Abschluss-Fortschritt ("wie viele ECTS fehlen mir noch?")
        "fehlen mir", "fehlen noch", "ects fehlen", "ects brauche",
        "noch brauche", "noch benötige", "abschließen", "abzuschließen",
        "studium abschließen", "wie viele ects fehlen", "wie viel fehlt",
        "wie viele ects habe", "wie viele ects bin", "erreichte ects",
        # Umgangssprachliche "Habe ich X schon gemacht?"-Formulierungen (#11)
        "hab ich", "habe ich", "hab ich schon", "habe ich schon",
        "schon gemacht", "schon absolviert", "schon gehabt",
        "bereits gemacht", "bereits absolviert", "schon belegt",
        "absolviert", "abgeschlossen",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in grade_keywords)


def _is_duration_question(question: str) -> bool:
    """
    Erkennt Fragen zur Studiendauer (§ 5 Dauer und Gliederung). Diese Info steckt
    in einem kurzen Prosa-Chunk, der von vielen 'Semesterstunden'-LVA-Chunks
    verdraengt wird – daher gesondert behandeln.
    """
    q = question.lower()
    duration_keywords = [
        "wie viele semester", "wie lange dauert", "wie lange geht",
        "dauer des studiums", "studiendauer", "regelstudienzeit",
        "wie viele semester dauert", "wieviele semester",
    ]
    return any(kw in q for kw in duration_keywords)


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

    # 1a. Zeitbasierte Frage → Persönliche KUSSS-Termine einspeisen.
    #     Leeren Treffer differenzieren: "kein Kalender" vs. "Kalender da, aber
    #     keine Termine im erfragten Zeitraum" (sonst falsche Aussage, Eval #14).
    if user_id and _is_valid_user_id(user_id) and is_time_based(question):
        events_text = query_events(question, user_id)
        if events_text:
            context_parts.append(f"KALENDER-EINTRAEGE:\n{events_text}")
        elif _user_has_any_events(user_id):
            context_parts.append(
                "KALENDER-STATUS: Es ist ein Kalender hinterlegt, aber im erfragten "
                "Zeitraum gibt es keine Termine."
            )
        else:
            context_parts.append(
                "KALENDER-STATUS: Fuer diesen Nutzer ist noch kein Kalender hinterlegt."
            )

    # 1b. Noten-Frage → Studienerfolg (Notennachweis) anhängen
    if user_id and _is_valid_user_id(user_id) and _is_grade_question(question):
        grades_text = query_grades(user_id)
        if grades_text:
            context_parts.append(f"DEIN STUDIENERFOLG:\n{grades_text}")

    # 2. Dynamische Steuerung der Ähnlichkeitssuche (Chunk-Menge steuern)
    #    Werte bewusst moderat, um unter dem Groq-TPM-Limit (6000) zu bleiben.
    duration_question = _is_duration_question(question)
    if duration_question:
        # Der § 5-Prosa-Chunk wird leicht von 'Semesterstunden'-LVAs verdraengt;
        # mehr Treffer holen und unten gezielt nach vorne sortieren.
        match_count = 18
    elif _is_list_question(question) or _is_full_curriculum_question(question):
        match_count = 14
    elif _is_structured_question(question):
        match_count = 10
    else:
        match_count = 8

    # Bei persoenlichen Noten-/Fortschrittsfragen kommt die Antwort aus
    # "DEIN STUDIENERFOLG"; dann reichen wenige Curriculum-Chunks als Kontext.
    if _is_grade_question(question):
        match_count = min(match_count, 6)

    # 3. Vektorsuche auf Curriculum- und Webdaten ausführen
    #    (search_text enthaelt bei Folgefragen zusaetzlich die vorige Nutzerfrage)
    results = search_jku_knowledge(
        search_text,
        study_program_id=study_program_id,
        match_count=match_count,
    )

    # 3b. Doppelte Chunks entfernen (die DB enthaelt teils duplizierte Eintraege,
    #     was den Kontext unnoetig aufblaeht und das Token-Limit sprengen kann).
    if results:
        seen = set()
        unique_results = []
        for r in results:
            content = r.get("content", "")
            if content and content not in seen:
                seen.add(content)
                unique_results.append(r)
        results = unique_results

    # 4. Suchergebnisse sortieren (Tabellen/Curriculum-Zeilen vor unstrukturierten Web-Daten ranken)
    if results:
        if duration_question:
            # Chunks, die die Studiendauer tatsaechlich nennen, nach ganz vorne.
            results.sort(key=lambda r: (
                0 if ("dauert" in r.get("content", "").lower()
                      or "dauer und gliederung" in r.get("content", "").lower())
                else 1
            ))
        elif _is_list_question(question) or _is_structured_question(question):
            results.sort(key=lambda r: (
                0 if r.get("metadata", {}).get("chunk_type") in ("curriculum_row", "overview_table")
                else 1
            ))

    # Name des aktuell gewaehlten Studiengangs (fuer Systemgrenzen-Hinweise im Prompt)
    selected_program = None
    if results:
        selected_program = results[0].get("metadata", {}).get("study_program")
    program_hint = (
        f'Der Nutzer hat aktuell den Studiengang "{selected_program}" ausgewaehlt. '
        f"Curriculum-Fragen beziehen sich auf diesen Studiengang. "
        f"Persoenliche Daten (KALENDER-EINTRAEGE und DEIN STUDIENERFOLG) gelten "
        f"unabhaengig vom gewaehlten Studiengang und werden IMMER verwendet, wenn vorhanden."
        if selected_program
        else "Der Nutzer hat einen Studiengang ueber den Filter ausgewaehlt."
    )

    # Curriculum-Chunks separat halten, damit sie bei einem Token-Limit-Fehler
    # (Groq 413) schrittweise reduziert werden koennen (Eval #18 "STEOP").
    def _context_text(n_chunks: int) -> str:
        parts = list(context_parts)
        if results and n_chunks > 0:
            chunks_text = "\n\n---\n\n".join(
                res["content"] for res in results[:n_chunks]
            )
            parts.append(f"CURRICULUM-INFORMATIONEN:\n{chunks_text}")
        return (
            "\n\n".join(parts)
            if parts
            else "Keine relevanten Informationen in der Wissensdatenbank gefunden."
        )

    # Strict System Prompt zur Einhaltung der JKU-Datenhierarchie definieren.
    # Der Kontext wird erst beim Bauen der Nachricht angehaengt (s. _build_messages).
    system_prompt_prefix = f"""Du bist ein hilfreicher Studien-Assistent fuer die JKU Linz.
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
   - WICHTIG bei mehrdeutigen Namen: Wird nach einem Fach X gefragt, nimm den
     Curriculum-Eintrag, dessen "Bezeichnung" GENAU X ist (z.B. "Software Engineering").
     Ignoriere laengere Eintraege, die X nur enthalten (z.B. "Methoden und Konzepte
     des Software Engineering" oder "Anwendungen des Software Engineering") sowie
     einzelne Lehrveranstaltungen (VL/UE/PR/PS) – diese sind Teil-Leistungen des Fachs.
     Beispiel: "Software Engineering" -> 12 ECTS (das Pflichtfach), nicht 3 oder 6.

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
   - MASSGEBLICH ist immer die Zeile "Erreichte ECTS: X" in der ZUSAMMENFASSUNG.
     Wenn der Nutzer selbst eine andere ECTS-Zahl behauptet (auch in vorherigen Nachrichten),
     IGNORIERE diese und verwende ausschliesslich den Wert aus "Erreichte ECTS". Korrigiere
     den Nutzer dabei freundlich ("Laut deinem Studienerfolg sind es X ECTS").
   - Bei Fragen nach Noten eines bestimmten Kurses: suche alle Eintraege die den gefragten Kursnamen enthalten. Liste nur diese auf, keine anderen Kurse.
   - Bei "wie viele ECTS": nenne EXAKT den Wert aus "Erreichte ECTS", zaehle nicht selbst.
   - Bei "Notendurchschnitt": nenne den Wert aus der ZUSAMMENFASSUNG.
   - Bei "wie viele ECTS fehlen mir / was fehlt mir noch": Das Bachelorstudium Wirtschaftsinformatik
     umfasst 180 ECTS. Rechne: 180 minus "Erreichte ECTS" = fehlende ECTS. Nenne NUR diese Zahl.
     Verwende NIEMALS eine vom Nutzer behauptete ECTS-Zahl fuer diese Rechnung.
     Liste KEINE konkreten fehlenden Kurse auf, da du nicht sicher weisst welche das sind.
     Empfehle stattdessen, den Studienfortschritt in KUSSS zu pruefen.

9. Kalender / Stundenplan / Termine:
   - Wenn "KALENDER-EINTRAEGE" im Kontext stehen, beantworte Fragen nach Stundenplan,
     Terminen, Pruefungen oder "diese/naechste Woche" DIREKT anhand dieser Eintraege
     (mit Datum, Uhrzeit und Raum).
   - Steht "KALENDER-STATUS: ... im erfragten Zeitraum gibt es keine Termine": sage
     freundlich, dass im gefragten Zeitraum (z.B. morgen bzw. diese Woche) keine Termine
     eingetragen sind. Behaupte dabei NICHT, es sei gar kein Kalender vorhanden.
   - Steht "KALENDER-STATUS: ... noch kein Kalender hinterlegt": sage, dass derzeit kein
     Kalender hochgeladen ist, und erklaere den Import: in KUSSS unter
     "Mein Stundenplan -> Export -> iCalendar" die .ics-Datei exportieren und sie im
     Stundenplan-Bereich der App hochladen.
   - Behaupte NIEMALS, du haettest keinen Zugriff auf persoenliche Termine/Stundenplaene.
     Persoenliche Termine gelten unabhaengig vom gewaehlten Studiengang.

10. Ton & Formulierung:
   - Antworte freundlich, klar und in vollstaendigen deutschen Saetzen.
   - Bleibe praezise und fasse dich kurz; keine internen Hinweise wie "laut Kontext"
     oder "im Kontext steht". Formuliere die Antwort direkt fuer die studierende Person.
   - Nenne im Antworttext NIEMALS interne Abschnittsnamen oder Label aus dem Kontext
     (z.B. KALENDER-EINTRAEGE, KALENDER-STATUS, CURRICULUM-INFORMATIONEN, DEIN STUDIENERFOLG).

KONTEXT:
"""

    # 5. Nachrichten zusammenbauen: System-Prompt + bisherige Historie + aktuelle Frage.
    #    Nur die letzten Turns mitschicken, um das Token-Budget zu schonen.
    recent_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    def _build_messages(n_chunks: int) -> list[dict]:
        system_prompt = system_prompt_prefix + _context_text(n_chunks)
        return (
            [{"role": "system", "content": system_prompt}]
            + recent_history
            + [{"role": "user", "content": question}]
        )

    # 6. API-Inferenz über Groq. Bei Token-Limit (413 "Request too large") den
    #    Curriculum-Kontext halbieren und erneut versuchen, statt mit Fehler abzubrechen.
    n_chunks = len(results)
    while True:
        try:
            chat_completion = client.chat.completions.create(
                messages=_build_messages(n_chunks),
                model="llama-3.1-8b-instant",
                temperature=0.2,  # Niedrige Temperatur für geringe Halluzinationsanfälligkeit
            )
            return chat_completion.choices[0].message.content
        except APIStatusError as exc:
            if getattr(exc, "status_code", None) == 413 and n_chunks > 1:
                n_chunks = n_chunks // 2
                print(f"ask_assistant: Token-Limit (413) – reduziere auf {n_chunks} Chunks und versuche erneut")
                continue
            raise


if __name__ == "__main__":
    user_frage = input("Deine Frage: ")
    antwort = ask_assistant(user_frage)
    print("\n" + "=" * 50)
    print(antwort)
    print("=" * 50)