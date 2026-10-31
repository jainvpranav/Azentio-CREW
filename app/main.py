from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import os
from dotenv import load_dotenv

load_dotenv()

from app.db import create_db_and_tables, engine, get_session
from app import models
from app.api import documents, transactions, statements, metrics as metrics_api, assessment


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
app.include_router(metrics_api.router)
app.include_router(assessment.router)

# Initialize database
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    print("Database initialized")


# ===================== Routes =====================

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


@app.get("/api/eval")
def eval_accuracy(session = Depends(get_session)):
    """
    Classification accuracy vs data_gen/output/ground_truth.json, if present
    (BUILD_PLAN.md section 7/8). Returns None accuracy when no ground truth
    file exists, e.g. in a real deployment with no synthetic demo data.
    """
    from eval.score import compute_score, load_ground_truth

    try:
        ground_truth = load_ground_truth()
    except FileNotFoundError:
        return {"accuracy": None, "message": "No ground_truth.json found. Run data_gen/generate.py first."}

    return compute_score(session, ground_truth)


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


@app.get("/review", response_class=HTMLResponse)
async def view_review(request: Request):
    """Review page (flags + classification audit trail)"""
    return templates.TemplateResponse("review.html", {"request": request, "page": "review"})


@app.get("/assessment", response_class=HTMLResponse)
async def view_assessment(request: Request):
    """Borrower assessment page: indicators, red flags, AI Reviewer findings, Individual/SME report."""
    return templates.TemplateResponse("assessment.html", {"request": request, "page": "assessment"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
