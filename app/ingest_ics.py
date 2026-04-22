import os
import re
from ics import Calendar
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)


def fix_encoding(text: str) -> str:
    """Korrigiert doppelt-kodierte UTF-8 Umlaute aus KUSSS (z.B. 'Ã¼' → 'ü')."""
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_summary(summary: str) -> dict:
    """Extrahiert course_type, course_name, professor, course_code aus dem SUMMARY-Feld.
    Beispiel: 'KS Einführung in Organisation / Markus Putz / (266002/2026S)'
    """
    pattern = r'^(\w+)\s+(.+?)\s*/\s*(.+?)\s*/\s*\((\S+)\)\s*$'
    match = re.match(pattern, summary.strip())
    if match:
        return {
            'course_type': match.group(1),
            'course_name': match.group(2).strip(),
            'professor':   match.group(3).strip(),
            'course_code': match.group(4),
        }
    return {
        'course_type': None,
        'course_name': summary.strip(),
        'professor':   None,
        'course_code': None,
    }


def detect_event_type(summary: str, description: str) -> str:
    text = (summary + ' ' + (description or '')).lower()
    if 'entfällt' in text or 'entfallt' in text:
        return 'Entfällt'
    if 'klausur' in text or 'exam' in text or 'prüfung' in text:
        return 'Prüfung'
    if 'präsentation' in text or 'presentation' in text:
        return 'Präsentation'
    if 'vorbesprechung' in text:
        return 'Vorbesprechung'
    if 'hackathon' in text:
        return 'Hackathon'
    if description and description.strip().lower() in ('hk', 'nk', 'nachklausur'):
        return 'Prüfung'
    return 'Einheit'


def ingest_ics(file_path: str, user_id: str):
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        cal = Calendar(f.read())

    events_data = []
    for event in cal.events:
        summary     = fix_encoding(event.name or '')
        description = fix_encoding(event.description) if event.description else None
        location    = fix_encoding(event.location) if event.location else None
        ical_uid    = event.uid
        start_dt    = event.begin.isoformat() if event.begin else None
        end_dt      = event.end.isoformat() if event.end else None

        parsed     = parse_summary(summary)
        event_type = detect_event_type(summary, description or '')

        events_data.append({
            'user_id':     user_id,
            'ical_uid':    ical_uid,
            'course_type': parsed['course_type'],
            'course_name': parsed['course_name'],
            'professor':   parsed['professor'],
            'course_code': parsed['course_code'],
            'event_type':  event_type,
            'description': description,
            'start_dt':    start_dt,
            'end_dt':      end_dt,
            'location':    location,
        })

    print(f"📅 {len(events_data)} Events gefunden. Lade hoch...")

    success = 0
    errors  = 0
    for ev in events_data:
        try:
            # upsert: bei erneutem Import werden Events aktualisiert statt dupliziert
            supabase.table('events').upsert(ev, on_conflict='ical_uid').execute()
            success += 1
        except Exception as e:
            print(f"  Fehler bei {ev['ical_uid']}: {e}")
            errors += 1

    print(f"✅ {success} Events hochgeladen, {errors} Fehler.")


if __name__ == "__main__":
    test_user_id = input("Deine Supabase User-ID: ")
    ingest_ics("data/kusss.ics", test_user_id)
