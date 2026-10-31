from enum import Enum
from decimal import Decimal
from typing import Optional, List
from datetime import date, datetime
from sqlmodel import SQLModel, Field


class TransactionCategory(str, Enum):
    """Transaction categories for classification"""
    SALARY = "SALARY"
    BUSINESS_RECEIPT = "BUSINESS_RECEIPT"
    POSSIBLE_BUSINESS_RECEIPT = "POSSIBLE_BUSINESS_RECEIPT"
    UNVERIFIED_CREDIT = "UNVERIFIED_CREDIT"
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


class TransactionCategoryGroup(str, Enum):
    """
    The six top-level categories from the handoff. The richer
    TransactionCategory enum above is kept (see DECISIONS.md D-002) because
    existing rules/tests depend on it and it carries information the
    handoff's own expense breakdown wants; this group is a read-only view
    over it, used by reports and behavioural analysis.
    """
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    SALARY = "SALARY"
    BUSINESS_RECEIPT = "BUSINESS_RECEIPT"
    REFUND_REVERSAL = "REFUND_REVERSAL"
    LOAN_EMI = "LOAN_EMI"
    COMMON_EXPENSE = "COMMON_EXPENSE"
    OTHER = "OTHER"  # loan disbursement, unverified credit, unclassified


class EntityType(str, Enum):
    """Whether a customer is analysed as an individual or an SME borrower."""
    INDIVIDUAL = "INDIVIDUAL"
    SME = "SME"


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


class ReviewRecommendation(str, Enum):
    """AI Reviewer outcomes (Phase 6). Never a fraud/default determination."""
    LIKELY_LEGITIMATE = "LIKELY_LEGITIMATE"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class HumanDecision(str, Enum):
    """Human reviewer's final call on an AI-reviewed case."""
    ACCEPTED = "accepted"          # agreed with AI recommendation
    OVERRIDDEN = "overridden"      # human disagreed, see decision_note
    PENDING = "pending"


# ===================== Database Models =====================

class Customer(SQLModel, table=True):
    """
    A borrower who may own one or more Accounts. Added per handoff's "Core
    transaction model" (customer_id) and Q1/Q2 - see ASSUMPTIONS.md A-001/A-002.
    Nullable link from Account (not required) so existing single-account
    flows keep working without a customer being created first.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    entity_type: EntityType = EntityType.INDIVIDUAL
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Account(SQLModel, table=True):
    """Bank account information"""
    id: Optional[int] = Field(default=None, primary_key=True)
    holder_name: str
    account_number: str = Field(index=True)
    bank_name: str
    account_type: str
    customer_id: Optional[int] = Field(default=None, foreign_key="customer.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Facility(SQLModel, table=True):
    """
    CC/OD facility metadata for an account. Must be supplied by an analyst -
    never inferred from transaction swings (handoff Phase 2 SME metrics).
    Missing facility/limit => CC/OD Utilization returns NOT_AVAILABLE.
    See ASSUMPTIONS.md A-003.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    facility_type: str  # "CC" or "OD"
    sanctioned_limit: Optional[Decimal] = None
    as_of_date: Optional[date] = None
    source_note: Optional[str] = None  # how the limit was obtained (manual entry, sanction letter, etc.)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    """Uploaded statement document"""
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    file_type: str  # pdf, csv, xlsx, json, png, jpg, jpeg
    sha256: Optional[str] = Field(default=None, index=True)  # detect re-upload
    status: DocumentStatus = DocumentStatus.UPLOADED
    pages_total: Optional[int] = None
    pages_parsed: Optional[int] = None
    errors: Optional[str] = None  # JSON list
    extraction_method: Optional[str] = None  # native_pdf, ocr_pdf, csv, json, image_ocr
    ocr_confidence: Optional[float] = None   # average OCR confidence 0-100, when OCR was used
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Statement(SQLModel, table=True):
    """Bank statement metadata"""
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    account_id: int = Field(foreign_key="account.id")
    period_start: date
    period_end: date
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    computed_closing: Optional[Decimal] = None
    reconciled: bool = False
    discrepancy: Optional[Decimal] = None
    discrepancy_rows: Optional[str] = None  # JSON
    currency: Optional[str] = None  # ISO 3-letter code, None if multi-currency or unknown


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
    pair_id: Optional[int] = None  # linked_transaction_id: reversal/refund original, transfer counterpart, etc.

    # Best-effort extraction from the raw description; never fabricated -
    # None means "not available", not "zero"/"unknown merchant". See
    # app/ingest/normalize.py:extract_transaction_metadata and ASSUMPTIONS.md A-009.
    counterparty: Optional[str] = None
    counterparty_account: Optional[str] = None
    reference_number: Optional[str] = None  # UTR / bank reference / RRN if present in narration
    transaction_type: Optional[str] = None  # UPI / NEFT / IMPS / RTGS / ATM / CASH / CHEQUE / ECS / NACH / OTHER
    currency: Optional[str] = None          # ISO 3-letter code; None = not determinable (flag for review)
    raw_debit: Optional[str] = None         # original debit text before normalization
    raw_credit: Optional[str] = None        # original credit text before normalization
    custom_metadata: Optional[str] = None   # JSON: unmapped institution-specific columns (Branch Code, etc.)
    source_data: Optional[str] = None       # JSON: complete original row {header: value} for audit


class Classification(SQLModel, table=True):
    """Transaction classification (append-only)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    txn_id: int = Field(foreign_key="transaction.id")
    category: TransactionCategory
    subcategory: Optional[str] = None  # e.g. groceries/dining/transport under COMMON_EXPENSE
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
    account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    flag_type: str  # RECON_MISMATCH, MISSING_MONTH, DUPLICATES_REMOVED, etc.
    severity: FlagSeverity
    message: str
    evidence: Optional[str] = None  # JSON txn ids
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RuleEvaluation(SQLModel, table=True):
    """
    Audit record for one borrower-assessment rule result (Phase 5).
    One row per (rule_id, account_id, period) evaluation, append-only -
    re-running the engine adds new rows rather than overwriting, so the
    same inputs + rule config are always reproducible from history.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: str
    rule_version: str
    account_id: int = Field(foreign_key="account.id", index=True)
    metric_name: str
    metric_value: Optional[float] = None  # None when NOT_AVAILABLE
    threshold_label: Optional[str] = None  # e.g. "<=40 / 40-55 / >55"
    result: str  # e.g. "lower_burden" / "elevated" / "higher_burden" / "NOT_AVAILABLE"
    period: str
    supporting_txn_ids: Optional[str] = None  # JSON list
    confidence: Optional[str] = None  # data-completeness label, not a probability
    limitations: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIReview(SQLModel, table=True):
    """
    AI Reviewer output for one flagged case (Phase 6). The LLM only produces
    the narrative/synthesis fields below; it never computes amounts, ratios
    or the deterministic rule result it is reviewing (those come from Flag /
    RuleEvaluation and are passed in as evidence, not regenerated).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str = Field(index=True)  # stable id, e.g. "FLAG-{flag_id}"
    flag_id: Optional[int] = Field(default=None, foreign_key="flag.id")
    account_id: int = Field(foreign_key="account.id", index=True)
    triggered_rule: str
    related_txn_ids: str  # JSON list
    observed_facts: str
    historical_comparison: str
    supporting_evidence: str
    contradicting_evidence: str
    possible_explanations: str
    unresolved_questions: str
    recommendation: ReviewRecommendation
    confidence: float
    escalation_reason: Optional[str] = None
    human_decision: HumanDecision = HumanDecision.PENDING
    human_decision_note: Optional[str] = None
    llm_model_name: Optional[str] = None  # None when the LLM step was not run (no provider configured)
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
    subcategory: Optional[str] = None
    classification_confidence: Optional[float] = None
    rule_id: Optional[str] = None
    reason: Optional[str] = None
    page: int
    row_index: int
    duplicate_of: Optional[int] = None
    counterparty: Optional[str] = None
    counterparty_account: Optional[str] = None
    reference_number: Optional[str] = None
    transaction_type: Optional[str] = None
    currency: Optional[str] = None
    custom_metadata: Optional[str] = None  # JSON string


class StatementResponse(SQLModel):
    """Statement with account info"""
    id: int
    account_id: int
    period_start: date
    period_end: date
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
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
    extraction_method: Optional[str] = None
    ocr_confidence: Optional[float] = None
