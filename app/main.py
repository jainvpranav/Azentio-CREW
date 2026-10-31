from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import os

from app.db import create_db_and_tables, engine, get_session
from app import models
from app.api import documents, transactions, statements


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

# Static files
template_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=template_dir)

# Include routers
app.include_router(documents.router)
app.include_router(transactions.router)
app.include_router(statements.router)

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
def list_accounts(session = Depends(get_session)):
    """List all accounts"""
    from sqlmodel import select
    accounts = session.exec(select(models.Account)).all()
    return accounts


@app.post("/api/reset")
def reset_database(session = Depends(get_session)):
    """Reset database (demo convenience)"""
    # Drop all tables
    models.SQLModel.metadata.drop_all(engine)
    create_db_and_tables()

    return {"message": "Database reset"}


# ===================== HTML Pages =====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Upload page"""
    return templates.TemplateResponse("upload.html", {"request": request, "page": "home"})


@app.get("/transactions", response_class=HTMLResponse)
async def view_transactions(request: Request):
    """Transactions page"""
    return templates.TemplateResponse("transactions.html", {"request": request, "page": "transactions"})


@app.get("/analysis", response_class=HTMLResponse)
async def view_analysis(request: Request):
    """Analysis page"""
    return templates.TemplateResponse("analysis.html", {"request": request, "page": "analysis"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
