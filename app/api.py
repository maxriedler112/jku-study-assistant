from fastapi import FastAPI, Header, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from assistant import ask_assistant
from search import supabase
from pipeline import process_studienerfolg
from typing import Optional
from ical_ingest import ingest_ics_text

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["User-ID", "Content-Type"],
)

@app.get("/")
def root():
    return {"message": "API läuft 🚀"}

@app.get("/programs")
def programs():
    """
    Liefert alle Studiengaenge, die tatsaechlich Inhalte (chunks) in Supabase haben.
    Das Frontend baut daraus dynamisch die Studiengang-Buttons.
    """
    try:
        resp = supabase.rpc("list_study_programs_with_content").execute()
        return {"programs": resp.data or []}
    except Exception as exc:
        print(f"GET /programs error: {exc}")
        return {"programs": []}


def get_study_progress_summary(user_id: str):
    resp = supabase.table("completed_courses").select("*").eq("user_id", user_id).execute()
    courses = resp.data or []
    passed = sum(1 for c in courses if c.get("passed", False))
    failed = len(courses) - passed
    ects_total = sum(c.get("ects", 0) for c in courses if c.get("passed", False))
    grades = [
        c.get("grade")
        for c in courses
        if c.get("passed", False) and isinstance(c.get("grade"), (int, float)) and c.get("grade") > 0
    ]
    grade_average = round(sum(grades) / len(grades), 1) if grades else 0

    return {
        "ects_total": round(ects_total, 1),
        "passed": passed,
        "failed": failed,
        "total": len(courses),
        "grade_average": grade_average,
    }


@app.post("/study-progress")
def study_progress_upload(
    request: Request,
    file: UploadFile = File(...),
    user_id: Optional[str] = Header(None)
):
    print(f"POST /study-progress request: method={request.method}, content-type={request.headers.get('content-type')}, user_id={user_id}")
    if not user_id:
        user_id = request.headers.get('user-id') or request.headers.get('User-ID')
    if not user_id:
        user_id = request.query_params.get('user_id')
    """
    Upload-Endpunkt für Studienerfolg-PDF/CSV.
    Verarbeitet die Datei und speichert die Noten in Supabase.
    """
    if not user_id or user_id == "test-user":
        return {
            "success": False,
            "message": "User-ID erforderlich"
        }
    
    try:
        file_bytes = file.file.read()
        result = process_studienerfolg(file_bytes, file.filename or "file", user_id)
        summary = get_study_progress_summary(user_id)
        
        return {
            "success": True,
            "message": f"{result['passed']} Kurse gespeichert",
            "data": summary
        }
    except ValueError as e:
        return {
            "success": False,
            "message": str(e)
        }
    except Exception as e:
        print(f"Upload error: {e}")
        return {
            "success": False,
            "message": "Fehler beim Verarbeiten der Datei"
        }

@app.get("/study-progress")
def study_progress(user_id: Optional[str] = Header(None)):
    """
    Liefert die Studienerfolgs-Daten für einen User (ECTS, Noten, Erfolgsquote, etc.)
    """
    if not user_id or user_id == "test-user":
        # Keine Daten für Test-User
        return {
            "ects_total": 0,
            "passed": 0,
            "failed": 0,
            "total": 0,
            "grade_average": 0
        }
    
    try:
        # Hole alle completed_courses für diesen User
        resp = supabase.table("completed_courses").select("*").eq("user_id", user_id).execute()
        courses = resp.data or []
        
        if not courses:
            return {
                "ects_total": 0,
                "passed": 0,
                "failed": 0,
                "total": 0,
                "grade_average": 0
            }
        
        # Berechne Statistiken
        passed = sum(1 for c in courses if c.get("passed", False))
        failed = len(courses) - passed
        ects_total = sum(c.get("ects", 0) for c in courses if c.get("passed", False))
        
        # Berechne Notendurchschnitt (nur bestandene Kurse)
        grades = [
            c.get("grade")
            for c in courses
            if c.get("passed", False) and isinstance(c.get("grade"), (int, float)) and c.get("grade") > 0
        ]
        grade_average = sum(grades) / len(grades) if grades else 0
        
        return {
            "ects_total": round(ects_total, 1),
            "passed": passed,
            "failed": failed,
            "total": len(courses),
            "grade_average": round(grade_average, 1)
        }
    except Exception as exc:
        print(f"GET /study-progress error: {exc}")
        return {
            "ects_total": 0,
            "passed": 0,
            "failed": 0,
            "total": 0,
            "grade_average": 0
        }


@app.post("/upload-ics")
async def upload_ics(data: dict):
    """
    Nimmt einen iCal-Text (.ics) entgegen, parst die Termine und speichert sie
    in Supabase 'events' unter der user_id des eingeloggten Nutzers.
    """
    ics_text = data.get("ics_text")
    user_id = data.get("user_id") or "test-user"
    if not ics_text:
        return {"saved": 0, "error": "Kein iCal-Inhalt erhalten."}
    try:
        saved = ingest_ics_text(ics_text, user_id)
        print(f"POST /upload-ics: {saved} Events fuer user_id={user_id} gespeichert")
        return {"saved": saved}
    except Exception as exc:
        print(f"POST /upload-ics error: {exc}")
        return {"saved": 0, "error": "iCal-Datei konnte nicht verarbeitet werden."}


@app.get("/events")
def events(user_id: str):
    """Liefert die gespeicherten Termine eines Nutzers fuer die Stundenplan-Anzeige."""
    try:
        resp = (
            supabase.table("events")
            .select("id,course_name,course_type,start_dt,end_dt,location")
            .eq("user_id", user_id)
            .order("start_dt")
            .execute()
        )
        return {"events": resp.data or []}
    except Exception as exc:
        print(f"GET /events error: {exc}")
        return {"events": []}


@app.post("/chat")
async def chat(data: dict):
    user_message = data.get("message")
    study_program_id = data.get("study_program_id")
    history = data.get("history") or []
    # user_id kommt vom eingeloggten Nutzer (Matrikelnummer oder UUID). Faellt auf
    # "test-user" zurueck (ungueltig -> persoenliche Daten werden dann nicht geladen).
    user_id = data.get("user_id") or "test-user"
    print(f"POST /chat received message: {user_message}, study_program_id: {study_program_id}, user_id: {user_id}, history_len: {len(history)}")

    try:
        response = ask_assistant(
            user_message,
            user_id=user_id,
            study_program_id=study_program_id,
            history=history,
        )
    except Exception as exc:
        print(f"POST /chat error: {exc}")
        return {
            "response": "Entschuldigung, beim Verarbeiten der Anfrage ist ein Fehler aufgetreten. Bitte versuche es erneut."
        }

    print(f"POST /chat sending response")
    return {"response": response}
