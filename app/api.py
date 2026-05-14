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

    response = ask_assistant(
        user_message,
        user_id="test-user",
        study_program_id=None,
    )

    return {"response": response}
