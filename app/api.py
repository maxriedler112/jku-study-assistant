from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.assistant import ask_assistant

class ChatRequest(BaseModel):
    message: str
    study_program_id: str | None = None
    user_id: str | None = None
    schedule_ics: str | None = None
    exams_ics: str | None = None

class ChatResponse(BaseModel):
    response: str

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
    return {"message": "JKU Study Assistant API running"}

@app.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest):
    if not data.message:
        raise HTTPException(status_code=400, detail="Message is required")

    try:
        response_text = ask_assistant(
            data.message,
            user_id=data.user_id,
            study_program_id=data.study_program_id,
            schedule_ics=data.schedule_ics,
            exams_ics=data.exams_ics,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"response": response_text}
