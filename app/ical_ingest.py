"""
ical_ingest.py – KUSSS iCal (.ics) parsen und in Supabase 'events' speichern.

Eigener, schlanker VEVENT-Parser: Die `ics`-Bibliothek (0.7.x) stuerzt am grossen
VTIMEZONE-Block der KUSSS-Exporte ab (RecursionError). Wir lesen daher nur die
VEVENT-Bloecke direkt und ignorieren VTIMEZONE.

KUSSS-SUMMARY-Format:
    "{Typ} {Kursname} / {Professor} / ({LVA-Nr}/{Semester})"
    z.B. "KS Einführung in die Mikroökonomie / Gerald Pruckner / (239703/2026S)"
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from search import supabase  # vorhandener Supabase-Client (bare-import-Stil)

_LVA_TYPES = {"VL", "UE", "KS", "KV", "SE", "PR", "PS", "VO", "AG", "IK", "KT", "PJ", "UV", "RE"}
_DEFAULT_TZ = "Europe/Vienna"
UPSERT_BATCH = 100


def _unfold(text: str) -> list[str]:
    """RFC5545-Line-Unfolding: Fortsetzungszeilen (beginnen mit Space/Tab) anhaengen."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n")
                 .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def _parse_dt(value: str, params: dict):
    """ICS-Datumswert in ein tz-bewusstes datetime umwandeln (ISO-faehig)."""
    value = value.strip()
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
        fmt = "%Y%m%dT%H%M%S" if "T" in value else "%Y%m%d"
        dt = datetime.strptime(value, fmt)
        tzid = params.get("TZID", _DEFAULT_TZ)
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            return dt.replace(tzinfo=ZoneInfo(_DEFAULT_TZ))
    except Exception:
        return None


def _parse_summary(summary: str):
    """Zerlegt die SUMMARY in (course_type, course_name, professor, course_code)."""
    parts = [p.strip() for p in summary.split(" / ")]
    head = parts[0] if parts else ""
    course_type, course_name = None, head
    tokens = head.split(" ", 1)
    if len(tokens) == 2 and tokens[0] in _LVA_TYPES:
        course_type, course_name = tokens[0], tokens[1].strip()
    professor = parts[1] if len(parts) >= 2 else None
    course_code = None
    if len(parts) >= 3:
        m = re.search(r"\(([^)]+)\)", parts[2])
        course_code = m.group(1) if m else parts[2]
    return course_type, course_name, professor, course_code


def parse_ics(ics_text: str) -> list[dict]:
    """Parst ICS-Text in eine Liste von Event-Dicts (Schema der events-Tabelle)."""
    events: list[dict] = []
    current: dict | None = None

    for line in _unfold(ics_text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and current.get("uid") and current.get("start_dt"):
                ct, cn, prof, code = _parse_summary(current.get("summary", ""))
                events.append({
                    "course_code": code,
                    "course_type": ct,
                    "course_name": cn or "(ohne Titel)",
                    "professor": prof,
                    "event_type": None,
                    "description": current.get("description") or None,
                    "start_dt": current["start_dt"],
                    "end_dt": current.get("end_dt"),
                    "location": current.get("location") or None,
                    "ical_uid": current["uid"],
                })
            current = None
            continue
        if current is None or ":" not in line:
            continue

        name_part, value = line.split(":", 1)
        name_bits = name_part.split(";")
        name = name_bits[0].upper()
        params = {}
        for p in name_bits[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.upper()] = v

        if name == "UID":
            current["uid"] = value.strip()
        elif name == "SUMMARY":
            current["summary"] = _unescape(value)
        elif name == "DESCRIPTION":
            current["description"] = _unescape(value)
        elif name == "LOCATION":
            current["location"] = _unescape(value)
        elif name == "DTSTART":
            dt = _parse_dt(value, params)
            current["start_dt"] = dt.isoformat() if dt else None
        elif name == "DTEND":
            dt = _parse_dt(value, params)
            current["end_dt"] = dt.isoformat() if dt else None

    return events


def store_events(events: list[dict], user_id: str) -> int:
    """Upsert der Events fuer einen user_id (Konflikt auf ical_uid -> idempotent)."""
    rows = [{**ev, "user_id": user_id} for ev in events if ev.get("start_dt")]
    saved = 0
    for i in range(0, len(rows), UPSERT_BATCH):
        batch = rows[i:i + UPSERT_BATCH]
        supabase.table("events").upsert(batch, on_conflict="ical_uid").execute()
        saved += len(batch)
    return saved


def ingest_ics_text(ics_text: str, user_id: str) -> int:
    """Komplett: ICS-Text parsen und fuer user_id speichern. Gibt Anzahl Events zurueck."""
    events = parse_ics(ics_text)
    return store_events(events, user_id)
