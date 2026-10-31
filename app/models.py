from enum import Enum
from decimal import Decimal
from typing import Optional, List
from datetime import date, datetime
from sqlmodel import SQLModel, Field


class TransactionCategory(str, Enum):
    """Transaction categories for classification"""
    SALARY = "SALARY"
    BUSINESS_RECEIPT = "BUSINESS_RECEIPT"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    REFUND = "REFUND"
    REVERSAL = "REVERSAL"
    LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT"
    LOAN_EMI = "LOAN_EMI"
    RENT = "RENT"
    UTILITIES = "UTILITIES"
    CARD_PAYMENT = "CARD_PAYMENT"
    OTHER_EXPENSE = "OTHER_EXPENSE"
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    BANK_CHARGES = "BANK_CHARGES"
    RETURNED_PAYMENT = "RETURNED_PAYMENT"
    INTEREST = "INTEREST"
    UNCLASSIFIED = "UNCLASSIFIED"


class DocumentStatus(str, Enum):
    """Status of document processing"""
    UPLOADED = "uploaded"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"


class FlagSeverity(str, Enum):
    """Flag severity levels"""
    INFO = "info"
    WARN = "warn"
    HIGH = "high"


# ===================== Database Models =====================

class Account(SQLModel, table=True):
    """Bank account information"""
    id: Optional[int] = Field(default=None, primary_key=True)
    holder_name: str
    account_number: str = Field(index=True)
    bank_name: str
    account_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    """Uploaded statement document"""
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    file_type: str  # pdf, csv, xlsx, json
    sha256: Optional[str] = Field(default=None, index=True)  # detect re-upload
    status: DocumentStatus = DocumentStatus.UPLOADED
    pages_total: Optional[int] = None
    pages_parsed: Optional[int] = None
    errors: Optional[str] = None  # JSON list
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Statement(SQLModel, table=True):
    """Bank statement metadata"""
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    account_id: int = Field(foreign_key="account.id")
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    computed_closing: Optional[Decimal] = None
    reconciled: bool = False
    discrepancy: Optional[Decimal] = None
    discrepancy_rows: Optional[str] = None  # JSON


class Transaction(SQLModel, table=True):
    """Individual transaction"""
    id: Optional[int] = Field(default=None, primary_key=True)
    statement_id: int = Field(foreign_key="statement.id")
    account_id: int = Field(foreign_key="account.id")
    document_id: int = Field(foreign_key="document.id")
    page: int
    row_index: int
    txn_date: date = Field(index=True)
    description: str
    description_norm: Optional[str] = None
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    balance: Optional[Decimal] = None
    raw_text: str
    fingerprint: Optional[str] = None  # for dedup
    duplicate_of: Optional[int] = Field(default=None, foreign_key="transaction.id")
    pair_id: Optional[int] = None  # for reversals/transfers


class Classification(SQLModel, table=True):
    """Transaction classification (append-only)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    txn_id: int = Field(foreign_key="transaction.id")
    category: TransactionCategory
    rule_id: Optional[str] = None
    reason: str
    confidence: float = 1.0
    source: str = "rule"  # rule, llm, user
    is_current: bool = True
    user_note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Flag(SQLModel, table=True):
    """Data quality & review flags"""
    id: Optional[int] = Field(default=None, primary_key=True)
    txn_id: Optional[int] = Field(default=None, foreign_key="transaction.id")
    statement_id: Optional[int] = Field(default=None, foreign_key="statement.id")
    flag_type: str  # RECON_MISMATCH, MISSING_MONTH, DUPLICATES_REMOVED, etc.
    severity: FlagSeverity
    message: str
    evidence: Optional[str] = None  # JSON txn ids
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ===================== Request/Response Models =====================

class TransactionResponse(SQLModel):
    """Transaction with classification"""
    id: int
    txn_date: date
    description: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    balance: Optional[Decimal]
    category: Optional[TransactionCategory] = None
    rule_id: Optional[str] = None
    reason: Optional[str] = None
    page: int
    row_index: int
    duplicate_of: Optional[int] = None


class StatementResponse(SQLModel):
    """Statement with account info"""
    id: int
    account_id: int
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    computed_closing: Optional[Decimal]
    reconciled: bool
    discrepancy: Optional[Decimal]


class DocumentResponse(SQLModel):
    """Document with parsing status"""
    id: int
    filename: str
    file_type: str
    status: DocumentStatus
    pages_total: Optional[int]
    pages_parsed: Optional[int]
    errors: Optional[List[dict]] = None
