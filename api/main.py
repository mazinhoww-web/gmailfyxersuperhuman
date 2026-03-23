"""
ARIA Email Assistant - FastAPI Backend
Exposes all Gmail AI processing logic as REST endpoints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

load_dotenv()

from api.routes import auth, emails, drafts, labels, snooze, followup

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
ALLOWED_ORIGINS = [
    FRONTEND_URL,
    "http://localhost:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    # Lovable preview URLs
    "https://*.lovable.app",
    "https://*.lovableproject.com",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    yield
    # Shutdown


app = FastAPI(
    title="ARIA Email Assistant API",
    description="AI-powered Gmail management backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.(lovable\.app|lovableproject\.com)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(emails.router, prefix="/emails", tags=["emails"])
app.include_router(drafts.router, prefix="/drafts", tags=["drafts"])
app.include_router(labels.router, prefix="/labels", tags=["labels"])
app.include_router(snooze.router, prefix="/snooze", tags=["snooze"])
app.include_router(followup.router, prefix="/followup", tags=["followup"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ARIA Email Assistant API"}
