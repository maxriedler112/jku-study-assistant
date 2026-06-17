from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from assistant import ask_assistant
from search import supabase

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
