from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import answers, nouns, questions, tts

app = FastAPI(title="French Beginner API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questions.router)
app.include_router(answers.router)
app.include_router(nouns.router)
app.include_router(tts.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
