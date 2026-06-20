from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from assistant import ask_assistant
from search import supabase
from ical_ingest import ingest_ics_text

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
