from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.assistant import ask_assistant

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

@app.post("/chat")
async def chat(data: dict):
    user_message = data.get("message")
    study_program_id = data.get("study_program_id")
    schedule_ics = data.get("schedule_ics")
    exams_ics = data.get("exams_ics")
    print(f"POST /chat received message: {user_message}, study_program_id: {study_program_id}, schedule_ics={'yes' if schedule_ics else 'no'}, exams_ics={'yes' if exams_ics else 'no'}")

    try:
        response = ask_assistant(
            user_message,
            user_id="test-user",
            study_program_id=study_program_id,
            schedule_ics=schedule_ics,
            exams_ics=exams_ics,
        )
    except Exception as exc:
        print(f"POST /chat error: {exc}")
        return {
            "response": "Entschuldigung, beim Verarbeiten der Anfrage ist ein Fehler aufgetreten. Bitte versuche es erneut."
        }

    print(f"POST /chat sending response")
    return {"response": response}
