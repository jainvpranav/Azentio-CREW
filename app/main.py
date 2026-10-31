from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

from app.db import create_db_and_tables, engine, get_session
from app import models


# Create app
app = FastAPI(title="Bank Statement Analyzer", version="0.1.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    print("Database initialized")


# ===================== Routes =====================

@app.get("/")
def root():
    return {"message": "Bank Statement Analyzer API v0.1.0"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/accounts", response_model=list[models.Account])
def list_accounts():
    """List all accounts"""
    from sqlmodel import select
    session = next(get_session())
    accounts = session.exec(select(models.Account)).all()
    return accounts


@app.get("/api/documents", response_model=list[models.DocumentResponse])
def list_documents():
    """List all uploaded documents with status"""
    from sqlmodel import select
    session = next(get_session())
    docs = session.exec(select(models.Document)).all()
    return docs


@app.post("/api/reset")
def reset_database():
    """Reset database (demo convenience)"""
    from sqlmodel import text
    session = next(get_session())

    # Drop all tables
    models.SQLModel.metadata.drop_all(engine)
    create_db_and_tables()

    return {"message": "Database reset"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
