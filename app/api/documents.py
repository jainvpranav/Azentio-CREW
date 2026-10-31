"""Document upload and management endpoints"""
import hashlib
import json
import os
from datetime import date
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlmodel import Session, select
import tempfile

from app.db import get_session
from app.models import Document, DocumentStatus, DocumentResponse, Account, Statement, Transaction
from app.ingest.pdf_parser import parse_pdf
from app.ingest.structured_parser import parse_csv, parse_excel


router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def calculate_sha256(file_bytes: bytes) -> str:
    """Calculate SHA256 hash of file"""
    return hashlib.sha256(file_bytes).hexdigest()


def parse_statement(file_path: str, file_type: str):
    """Dispatch to appropriate parser based on file type"""
    if file_type == "pdf":
        return parse_pdf(file_path)
    elif file_type == "csv":
        return parse_csv(file_path)
    elif file_type in ["xlsx", "xls"]:
        return parse_excel(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


@router.post("/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_session)
):
    """
    Upload one or more bank statement files.
    Supported formats: PDF, CSV, XLSX, XLS
    """
    results = []

    for file in files:
        try:
            # Determine file type
            file_name = file.filename
            file_ext = file_name.split(".")[-1].lower()

            if file_ext == "pdf":
                file_type = "pdf"
            elif file_ext == "csv":
                file_type = "csv"
            elif file_ext in ["xlsx", "xls"]:
                file_type = "xlsx"
            else:
                results.append({
                    "filename": file_name,
                    "status": "failed",
                    "error": "unsupported_file_type"
                })
                continue

            # Read file into memory
            file_bytes = await file.read()
            file_sha256 = calculate_sha256(file_bytes)

            # Check for re-upload
            existing = session.exec(
                select(Document).where(Document.sha256 == file_sha256)
            ).first()
            if existing:
                results.append({
                    "filename": file_name,
                    "status": "skipped",
                    "message": f"Already uploaded as {existing.filename}"
                })
                continue

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            try:
                # Parse statement
                parsed = parse_statement(tmp_path, file_type)

                # Create Account if not exists
                account_number = parsed.account_number or f"UNKNOWN_{file_sha256[:8]}"
                account = session.exec(
                    select(Account).where(Account.account_number == account_number)
                ).first()
                if not account:
                    account = Account(
                        holder_name=parsed.holder_name or "Unknown",
                        account_number=account_number,
                        bank_name=parsed.bank_name or "Unknown",
                        account_type="unknown"
                    )
                    session.add(account)
                    session.commit()
                    session.refresh(account)

                # Create Document
                doc_status = DocumentStatus.PARSED if not parsed.errors else DocumentStatus.PARTIAL
                document = Document(
                    filename=file_name,
                    file_type=file_type,
                    sha256=file_sha256,
                    status=doc_status,
                    pages_total=parsed.pages_total,
                    pages_parsed=parsed.pages_parsed,
                    errors=json.dumps([{"page": e.page, "reason": e.reason} for e in parsed.errors]) if parsed.errors else None
                )
                session.add(document)
                session.commit()
                session.refresh(document)

                # Create Statement
                if parsed.transactions:
                    statement = Statement(
                        document_id=document.id,
                        account_id=account.id,
                        period_start=parsed.period_start or parsed.transactions[0].txn_date,
                        period_end=parsed.period_end or parsed.transactions[-1].txn_date,
                        opening_balance=parsed.opening_balance,
                        closing_balance=parsed.closing_balance,
                    )
                    session.add(statement)
                    session.commit()
                    session.refresh(statement)

                    # Create Transactions
                    for parsed_txn in parsed.transactions:
                        txn = Transaction(
                            statement_id=statement.id,
                            account_id=account.id,
                            document_id=document.id,
                            page=parsed_txn.page,
                            row_index=parsed_txn.row_index,
                            txn_date=parsed_txn.txn_date,
                            description=parsed_txn.description,
                            description_norm=parsed_txn.description.upper().replace(" ", ""),
                            debit=parsed_txn.debit,
                            credit=parsed_txn.credit,
                            balance=parsed_txn.balance,
                            raw_text=parsed_txn.raw_text,
                        )
                        session.add(txn)
                    session.commit()

                results.append({
                    "filename": file_name,
                    "status": "parsed",
                    "document_id": document.id,
                    "transactions_count": len(parsed.transactions),
                    "pages_parsed": parsed.pages_parsed,
                    "pages_total": parsed.pages_total,
                    "errors": parsed.errors if parsed.errors else []
                })

            finally:
                os.unlink(tmp_path)

        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": str(e)
            })

    return {"results": results}


@router.get("/", response_model=List[DocumentResponse])
def list_documents(session: Session = Depends(get_session)):
    """List all documents"""
    documents = session.exec(select(Document)).all()

    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            status=doc.status,
            pages_total=doc.pages_total,
            pages_parsed=doc.pages_parsed,
            errors=json.loads(doc.errors) if doc.errors else None,
        )
        for doc in documents
    ]


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: int, session: Session = Depends(get_session)):
    """Get document details"""
    doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        pages_total=doc.pages_total,
        pages_parsed=doc.pages_parsed,
        errors=json.loads(doc.errors) if doc.errors else None,
    )
