# Bank Statement Analyzer

A lightweight, deterministic financial statement analysis tool built with FastAPI, designed for analyzing bank statements (PDF, CSV, Excel) and classifying transactions.

**Version:** 0.1.0 (Level 1 - MVP)

---

## 🎯 Features

### Phase 1: Foundation
- ✅ FastAPI backend with SQLModel ORM
- ✅ SQLite database (upgradeable to PostgreSQL)
- ✅ Data models for documents, statements, transactions, classifications, flags

### Phase 2: Ingestion
- ✅ **PDF Parser:** Table extraction using `pdfplumber`
- ✅ **CSV/Excel Parser:** Fuzzy column matching for flexible headers
- ✅ **Normalization:** Dates, amounts, descriptions
- ✅ **Deduplication:** SHA256-based file hash, fingerprint-based transaction dedup
- ✅ **Auto-Account Creation:** Infer accounts from statements

### Phase 3: Preprocessing
- ✅ **Reconciliation:** Verify opening + txns = closing (statement & row-level)
- ✅ **Deduplication:** Mark overlapping statement duplicates
- ✅ **Coverage Analysis:** Month-by-month coverage (full/partial/missing)

### Phase 4: UI
- ✅ **Upload Page:** Drag-drop, multi-file support, real-time feedback
- ✅ **Transactions View:** Filterable table, inline reclassification
- ✅ **Analysis Dashboard:** Summary metrics, document status
- ✅ **Responsive Design:** Mobile-friendly HTML + Alpine.js

### Phase 5: Business Engine
- ✅ **Classification Rules:** 15 deterministic rules (salary, loans, utilities, etc.)
- ✅ **Metrics:** Monthly credits/debits, estimated income, recurring obligations
- ✅ **Data Quality Flags:** Reconciliation mismatches, large deposits, returns, etc.
- ✅ **Append-Only History:** User corrections preserved

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
# Clone the repo
cd azentio-crew

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run Locally

```bash
python -m app.main
```

The API will be available at **http://localhost:8000**

- 🏠 Homepage: http://localhost:8000/
- 📋 API Docs: http://localhost:8000/docs
- 📤 Upload: http://localhost:8000/
- 📊 Transactions: http://localhost:8000/transactions
- 📈 Analysis: http://localhost:8000/analysis

---

## 📁 Project Structure

```
app/
├── main.py                  # FastAPI app + HTML routes
├── db.py                    # Database session management
├── models.py                # SQLModel table definitions
├── static/
│   └── style.css            # Responsive styling
├── templates/
│   ├── base.html            # Base layout
│   ├── upload.html          # File upload UI
│   ├── transactions.html    # Transaction table + filter
│   └── analysis.html        # Dashboard
├── ingest/
│   ├── pdf_parser.py        # PDF table extraction
│   ├── structured_parser.py # CSV/Excel parsing
│   └── normalize.py         # Date/amount normalization
├── pipeline/
│   ├── reconcile.py         # Statement reconciliation
│   ├── dedupe.py            # Duplicate detection
│   ├── coverage.py          # Month coverage analysis
│   ├── classify.py          # Rule-based classification
│   ├── metrics.py           # Financial metrics
│   └── flags.py             # Data quality flags
└── api/
    ├── documents.py         # Upload + document endpoints
    ├── transactions.py      # Transaction list + reclassify
    ├── statements.py        # Preprocessing endpoints
    └── metrics.py           # Classification + metrics endpoints
```

---

## 🔌 API Endpoints

### Documents
```
POST   /api/documents/upload           # Upload PDF/CSV/XLSX
GET    /api/documents/                 # List documents
GET    /api/documents/{id}             # Get document details
```

### Transactions
```
GET    /api/transactions/              # List with filtering
GET    /api/transactions/{id}          # Get transaction
POST   /api/transactions/{id}/reclassify  # User correction
```

### Statements
```
POST   /api/statements/process-all     # Full pipeline
POST   /api/statements/{id}/reconcile  # Reconcile
GET    /api/statements/{id}            # Get statement
POST   /api/statements/account/{id}/dedupe
GET    /api/statements/account/{id}/coverage
```

### Metrics
```
POST   /api/metrics/classify-all       # Run classifier
GET    /api/metrics/account/{id}       # All metrics
GET    /api/metrics/account/{id}/income # Estimated income
POST   /api/metrics/flags/generate     # Generate flags
GET    /api/metrics/flags              # Flag queue
```

### Admin
```
GET    /api/accounts                   # List accounts
POST   /api/reset                      # Clear database
```

---

## 💡 Key Design Principles

1. **Traceability:** Every transaction keeps source reference (page, row, doc_id)
2. **Deterministic First:** Rules-based classification, no LLM by default
3. **Append-Only:** Corrections create new records, originals preserved
4. **Money is Decimal:** No float arithmetic (avoids rounding errors)
5. **Flag, Don't Accuse:** Issues marked for review, never labeled "fraud"
6. **Reconciliation:** Opening + credits - debits = closing (with tolerance)

---

## 📊 Classification Rules (15 Rules)

| Order | Category | Trigger |
|-------|----------|---------|
| 1 | REVERSAL | REV/REVERSAL/RETURN in description |
| 2 | REFUND | REFUND/RFND/CASHBACK keyword |
| 3-4 | INTERNAL_TRANSFER | SELF/SWEEP/OWN A/C or counterparty match |
| 5 | LOAN_DISBURSEMENT | LOAN DISB/DISBURSAL keyword |
| 6 | RETURNED_PAYMENT | RETURN/BOUNCE/INSUFF/ECS RTN |
| 7 | SALARY | SAL/SALARY/PAYROLL keyword |
| 8 | LOAN_EMI | EMI/NACH/ECS/LOAN/ACH D |
| 9 | RENT | RENT keyword |
| 10 | UTILITIES | BESCOM, Airtel, Jio, etc. |
| 11 | CARD_PAYMENT | CC PAYMENT/CREDIT CARD |
| 12 | CASH_DEPOSIT/WITHDRAWAL | CASH DEP/CDM or ATM/CASH WDL |
| 13 | CHARGES/INTEREST | CHGS/FEE or INT.PD/INTEREST |
| 14 | BUSINESS_RECEIPT | UPI/NEFT/IMPS/RTGS from 3rd party |
| 15 | OTHER_EXPENSE | Remaining debits |
| — | UNCLASSIFIED | No match (confidence 0) |

---

## 🔄 Data Flow

```
PDF/CSV/XLSX Upload
       ↓
[Parse → Extract Txns]
       ↓
[Create Account/Statement/Txn]
       ↓
[Deduplicate (fingerprint)]
       ↓
[Reconcile (balance check)]
       ↓
[Classify (15 rules)]
       ↓
[Generate Flags]
       ↓
[Compute Metrics]
       ↓
[Display on UI]
```

---

## 🗄️ Database Schema

| Table | Purpose |
|-------|---------|
| `document` | Uploaded file metadata + parsing status |
| `account` | Bank account (holder, number, bank name) |
| `statement` | Statement period + opening/closing balance |
| `transaction` | Individual debit/credit with fingerprint |
| `classification` | Append-only history of category assignments |
| `flag` | Data quality issues & review requests |

All tables use `Decimal` for money (no float), `date` for dates (no datetime).

---

## 🚢 Deployment

### Docker (Coming Soon)
```bash
docker build -t bank-analyzer .
docker run -p 8000:8000 bank-analyzer
```

### Heroku / Railway
1. Set `DATABASE_URL` env var to PostgreSQL connection string
2. Push to git remote
3. Server starts on port 8000

### Local + SQLite
- Default: `statements.db` in project root
- Reset with `POST /api/reset`

---

## 📝 Future Enhancements (Level 2+)

- [ ] LLM-assisted suggestions for unclassified txns (confidence capped at 0.6)
- [ ] Recurring pattern detection (salary clusters despite name changes)
- [ ] Refund/reversal pairing logic
- [ ] Self-employed mode (business receipts as income)
- [ ] Interactive rules editor in UI
- [ ] Report generation (PDF/Excel)
- [ ] Multi-language support
- [ ] PostgreSQL by default
- [ ] Authentication & multi-user
- [ ] Webhook notifications for flags

---

## 🧪 Testing

```bash
# Run tests (coming soon)
pytest tests/

# Test with sample data
python data_gen/generate.py
```

---

## 📄 License

MIT

---

## 🤝 Contributing

1. Create a feature branch
2. Make changes
3. Commit with clear messages
4. Open a PR

---

## ❓ FAQ

**Q: Is this production-ready?**  
A: No. This is Level 1 MVP. For production, add tests, PostgreSQL, auth, and error handling.

**Q: Can I use it with live banking data?**  
A: Yes, but be careful with credentials. The app runs locally, so data stays on your machine.

**Q: How do I add a new classification rule?**  
A: Edit `app/pipeline/classify.py`, add a new `if` branch in `classify_transaction()`.

**Q: Can I use this for credit scoring?**  
A: Not recommended. Use with proper financial disclaimers.

**Q: What's the max file size?**  
A: Depends on your system RAM. Tested up to 50MB PDF. Optimize with streaming for larger files.

---

**Built with ❤️ by Claude + Pranav**

Questions? Check the BUILD_PLAN.md for design decisions.
