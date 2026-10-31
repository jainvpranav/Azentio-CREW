# Bank Statement & Financial Analysis — Build Plan (Level 1, designed for Levels 2+)

> Audience: coding agents + a team of 3. Stack: Python 3.11, FastAPI, SQLite (SQLModel), pdfplumber, pandas, lightweight HTML frontend (Jinja2 + HTMX + Alpine, served by FastAPI).
> Judges test **live behaviour**, not slides. Every number on screen must be clickable down to the transactions that produced it.

---

## 0. Non-negotiable principles (read before writing any code)

1. **Traceability over cleverness.** Every transaction keeps `document_id`, `page`, `row_index`, `raw_text`. Every classification keeps `rule_id` + human readable `reason`. Every metric returns `included[]` and `excluded[]` with reasons.
2. **Never invent data.** Missing month = `missing`, not `0`. Unparseable page = surfaced error, never silently skipped.
3. **Flag, don't accuse.** Unusual transactions go to a "Needs review" queue. The word "fraud" never appears as a label.
4. **Corrections are append-only.** A user reclassification creates a new classification row; the original is preserved and visible.
5. **Money is `Decimal`**, never float. Dates are `date`. Account numbers are masked in UI (`XXXX1234`).
6. **Deterministic first, LLM second.** Rules classify; an LLM may only *suggest* for unresolved transactions, tagged `source=llm`.

---

## 1. Repo layout

```
app/
  main.py                 # FastAPI app, routers, static + templates
  db.py                   # SQLModel engine/session
  models.py               # tables (section 2)
  ingest/
    router.py             # detect file type + layout, dispatch
    pdf_layout_a.py       # bank A parser (table based)
    pdf_layout_b.py       # bank B parser (text/regex based)
    structured.py         # CSV / XLSX / JSON
    normalize.py          # dates, amounts, Dr/Cr, description cleaning
  pipeline/
    reconcile.py          # opening + txns = closing, per-row running balance check
    dedupe.py             # duplicates + overlapping statements
    coverage.py           # months present / partial / missing
    classify.py           # ordered rule engine (section 4)
    pairing.py            # refund/reversal + internal transfer pairing
    metrics.py            # section 5, every fn returns MetricResult
    flags.py              # review flags (section 6)
    llm_assist.py         # optional suggestions for UNCLASSIFIED only
  api/                    # routers: documents, transactions, metrics, flags
  templates/ + static/
data_gen/
  generate.py             # synthetic statements + ground_truth.json
  scenarios.py            # planted edge cases (section 7)
eval/
  score.py                # classification accuracy vs ground truth
tests/
```

---

## 2. Data model

| Table | Key fields |
|---|---|
| `Document` | id, filename, file_type (pdf/csv/xlsx/json), layout_detected, status (`parsed`/`partial`/`failed`), pages_total, pages_parsed, errors (JSON list of `{page, reason}`), sha256 (detect exact re-upload) |
| `Account` | id, holder_name, account_number, bank_name, account_type |
| `Statement` | id, document_id, account_id, period_start, period_end, opening_balance, closing_balance, computed_closing, reconciled (bool), discrepancy (Decimal), discrepancy_rows (JSON) |
| `Transaction` | id, statement_id, account_id, document_id, page, row_index, txn_date, description, description_norm, debit, credit, balance, raw_text, fingerprint, duplicate_of (nullable FK), pair_id (nullable) |
| `Classification` | id, txn_id, category, rule_id, reason, confidence, source (`rule`/`llm`/`user`), is_current, created_at, user_note |
| `Flag` | id, txn_id (nullable), statement_id (nullable), type, severity (`info`/`warn`/`high`), message, evidence (JSON txn ids) |

**Categories (enum):** `SALARY`, `BUSINESS_RECEIPT`, `INTERNAL_TRANSFER`, `REFUND`, `REVERSAL`, `LOAN_DISBURSEMENT`, `LOAN_EMI`, `RENT`, `UTILITIES`, `CARD_PAYMENT`, `OTHER_EXPENSE`, `CASH_DEPOSIT`, `CASH_WITHDRAWAL`, `BANK_CHARGES`, `RETURNED_PAYMENT`, `INTEREST`, `UNCLASSIFIED`.

Metrics are **computed on read** from current classifications (dataset is small), so a correction recalculates everything for free.

---

## 3. Ingestion

### 3.1 Detection
- CSV/XLSX/JSON → `structured.py`, column mapping by fuzzy header match (`date|txn date|value date`, `narration|description|particulars`, `withdrawal|debit|dr`, `deposit|credit|cr`, `balance`).
- PDF → try each layout parser's `can_parse(first_page_text)` (bank name / header signature). No match → `status=failed`, reason `unknown_layout` (shown in UI).

### 3.2 PDF parsing rules
- Process **page by page**. Each page yields `rows[]` or an error. Page with zero rows but non-header text → error `no_transactions_extracted`. Image-only page (no text layer) → error `no_text_layer_scanned_page`.
- Header block extraction: holder, account number, bank, period, opening/closing balance. Missing header fields are `null` + an error entry, never guessed.
- Multi-line descriptions: a row without date continues the previous row's description.
- Amount normalisation: strip `₹`, `,`, `INR`; handle `Dr`/`Cr` suffix; handle single amount column + type column.
- Dates: support `DD/MM/YYYY`, `DD-MM-YY`, `DD MMM YYYY`. Default is day-first (Indian banks).

### 3.3 Reconciliation (`reconcile.py`)
- Statement level: `opening + Σcredit − Σdebit == closing` (tolerance ₹0.01). Store `computed_closing`, `discrepancy`.
- Row level: `prev_balance + credit − debit == balance`. Collect mismatching rows into `discrepancy_rows` → show the exact row where the chain breaks (usually a parsing miss or a missing page).

---

## 4. Classification engine (`classify.py`)

Ordered rules; **first match wins**; each rule returns `(category, rule_id, reason, confidence)`. Run pairing first, because pairing outcomes override keyword guesses.

`description_norm` = uppercase, strip ref numbers / UTR / dates / long digit runs, collapse whitespace. Keep raw for display.

| Order | rule_id | Logic | Reason template |
|---|---|---|---|
| 1 | `REV_PAIR` | Credit and debit of same amount, same account, within 7 days, one has `REV|REVERSAL|RETURN|REVERSED` | "Reversal of txn #{id} on {date} for ₹{amt}" |
| 2 | `REFUND_KW` | Credit with `REFUND|RFND|CASHBACK|CHARGEBACK`; try pairing with earlier debit to same merchant | "Refund from {merchant}; paired with #{id}" or "Refund keyword, no original found" |
| 3 | `XFER_PAIR` | Debit in account A and credit in account B (both uploaded, same holder), same amount, ±1 day | "Matched to credit #{id} in your account XXXX{last4}" |
| 4 | `XFER_SELF` | Counterparty name ≈ holder name (token overlap ≥ 0.8) or `SELF|OWN A/C|SWEEP|FD` or counterparty account matches an uploaded account | "Counterparty matches account holder name" |
| 5 | `LOAN_DISB` | Credit with `LOAN DISB|DISBURSAL|LOAN A/C CR` | "Loan disbursement, excluded from income" |
| 6 | `RETURNED` | `RETURN|BOUNCE|INSUFF|ECS RTN|NACH RTN` + charge | "Returned payment / bounce" |
| 7 | `SALARY_RECUR` | Credit cluster recurring monthly (gap 25–35 days), amount within ±15% of cluster median, ≥2 occurrences, AND (`SAL|SALARY|PAYROLL` keyword OR same day-of-month band ±3). **Clusters are built on amount + timing, not description**, so employer/payroll provider renames stay in one cluster | "Recurring monthly credit (n={n}, ~₹{median}, day {d}); description varies: {variants}" |
| 8 | `EMI_RECUR` | Debit, `EMI|NACH|ECS|LOAN|ACH D` OR same amount ±1% monthly ≥2 times to same counterparty | "Recurring ₹{amt} debit monthly to {cp}" |
| 9 | `RENT` | `RENT` keyword or recurring same-amount debit to individual early in month | |
| 10 | `UTILITIES` | Merchant list: BESCOM, electricity, water, gas, Airtel, Jio, BSNL, ACT, broadband, DTH | |
| 11 | `CARD_PAY` | `CC PAYMENT|CREDIT CARD|CARD DUES` | |
| 12 | `CASH_DEP` / `CASH_WDL` | `CASH DEP|CDM|BY CASH` / `ATM|CASH WDL` | |
| 13 | `CHARGES` / `INTEREST` | `CHGS|FEE|GST ON` / `INT.PD|INTEREST` | |
| 14 | `BIZ_RECEIPT` | Remaining credits via UPI/NEFT/IMPS/RTGS from third parties | "Third party credit from {cp}, not salary/transfer/refund" |
| 15 | `OTHER_EXP` | Remaining debits | |
| — | `UNCLASSIFIED` | Anything else → optionally `llm_assist` suggestion (`source=llm`, confidence capped at 0.6, reason required) | |

**Self-employed mode:** if no salary cluster exists, the profile is `self_employed` and business receipts drive income.

---

## 5. Metrics (`metrics.py`)

Every metric returns:
```python
class MetricResult(BaseModel):
    name: str
    value: Decimal | None        # None if not computable
    period: str | None           # "2026-07" or "Jun–Sep 2026"
    method: str                  # plain-English formula
    included: list[TxnRef]       # id, date, desc, amount, category
    excluded: list[ExcludedRef]  # + exclusion_reason
    caveats: list[str]           # e.g. "August missing, not counted as zero"
```

| Metric | Definition |
|---|---|
| Monthly credits (gross) | Σ credits per month, all txns, duplicates removed |
| Monthly credits (adjusted) | Gross minus internal transfers, refunds, reversals, loan disbursements |
| Monthly debits (adjusted) | Gross debits minus internal transfers out, reversed debits |
| Estimated income (salaried) | Median of monthly SALARY totals over available months |
| Estimated income (self-employed) | Median of monthly BUSINESS_RECEIPT totals over **complete** months; trim max month if ≥ 2× median; show volatility (coefficient of variation) |
| Recurring obligations | Σ monthly EMI + RENT + other recurring debits (latest observed amount per series) |
| Net cash flow | Adjusted credits − adjusted debits, per month |
| Balance trend | Month-end balance, avg daily balance (carry forward), min balance, days below ₹X threshold |
| Obligation-to-income ratio | Recurring obligations ÷ estimated income (bonus, credit analysts love it) |

Partial / missing months are excluded from averages and listed in `caveats`.

---

## 6. Dedupe, coverage and flags

**Dedupe:** `fingerprint = hash(account_id, txn_date, debit, credit, balance, description_norm[:40])`. If two statements of the same account overlap, keep the first occurrence and set `duplicate_of` on the rest (not deleted, shown greyed out with reason). Same `sha256` upload → reject with message "already uploaded as {filename}".

**Coverage:** per account, month grid from min to max date: `full` / `partial` (statement period cuts the month) / `missing`. Show it as a heatmap strip.

**Flags (Level 1 minimum, extend in Level 2):**
- `RECON_MISMATCH` (high), `MISSING_MONTH` (warn), `DUPLICATES_REMOVED` (info), `PAGE_FAILED` (high)
- `LARGE_CASH_DEPOSIT`: cash deposit > 2× median monthly income or > ₹2L
- `ROUND_FIGURE_SPIKE`: round amounts (multiple of 10,000) credited in the last 30 days of coverage
- `LOW_BALANCE`: ≥ 5 days below threshold in a month
- `INCOME_DECLINE`: last 3 month income < 70% of prior 3 month income
- `RETURNED_PAYMENT`: any bounce

All flags say "requires analyst review", never "fraud".

---

## 7. Synthetic data (`data_gen/`) — this is your demo AND your test suite

Generate with `reportlab` (PDFs) + pandas (CSV/XLSX/JSON). Also emit `ground_truth.json` (`txn key → expected category`).

| File | Planted scenarios |
|---|---|
| `bankA_savings_apr_jun.pdf` (layout A, table) | Salary "ACME TECH PVT LTD SAL APR" → payroll switch to "RAZORPAYX PAYROLL ACME" in June; ₹50,000 monthly transfer to own current account; Amazon refund paired with earlier debit |
| `bankA_savings_jun_aug.pdf` | Overlaps June → duplicate test |
| `bankB_current_apr_sep.pdf` (layout B, text) | Receives the ₹50k transfers; SME receipts from 8+ counterparties with irregular amounts; loan disbursement ₹5L; EMI ₹18,450 monthly; a NACH bounce; **July missing**; large cash deposit + round figure credits in final weeks |
| `bankB_scanned_page.pdf` | One image only page → must show `PAGE_FAILED` |
| `bankA_broken_balance.pdf` | One row's balance off by ₹1,000 → `RECON_MISMATCH` pointing at that row |
| `card_spend.csv`, `wallet.json`, `ledger.xlsx` | Structured inputs, different column names |

`eval/score.py` prints per-category precision/recall vs ground truth. Put that number on the dashboard ("Classification accuracy on test set: 96%"); the brief explicitly rewards measurable accuracy.

---

## 8. API

```
POST   /documents                      multipart upload (many files) → per-file status + errors
GET    /documents                      list with status, pages parsed/total, errors
GET    /accounts                       accounts + coverage grid
GET    /statements/{id}                header + reconciliation result
GET    /transactions?account&month&category&flagged
GET    /transactions/{id}              full detail + classification history + source ref
POST   /transactions/{id}/reclassify   {category, note} → new Classification(source=user); returns recomputed metrics
GET    /metrics?account&month          list[MetricResult]
GET    /metrics/{name}                 single metric with full breakdown
GET    /flags
GET    /eval                           accuracy vs ground truth (if present)
POST   /reset                          wipe DB (demo convenience)
```

---

## 9. UI (4 screens)

1. **Upload** — drag and drop; table of files with status pill, `pages_parsed/pages_total`, expandable error list per page.
2. **Transactions** — filterable table: date, description, debit, credit, balance, category chip (hover = reason + rule_id), source link "Doc · p.3 · row 12", duplicate rows greyed with reason. Inline dropdown to reclassify → modal for note → toast "Estimated income changed ₹82,000 → ₹1,32,000".
3. **Analysis** — metric cards; clicking a card opens a drawer with method, included, excluded (with reasons), caveats. Monthly credits/debits bar chart, balance line chart, coverage heatmap.
4. **Review** — flags queue + classification audit trail (original vs current, who/when/why).

---

## 10. 3 hour split (team of 3)

| Time | P1: Ingestion | P2: Brain | P3: API + UI |
|---|---|---|---|
| 0:00–0:30 | `data_gen` skeleton + layout A PDF | models.py, normalize.py, category enum | FastAPI scaffold, DB, upload endpoint, Upload screen |
| 0:30–1:30 | Layout A + B parsers, structured parser, page errors | classify rules 1–8 + pairing, run against ground truth | Transactions screen + reclassify flow |
| 1:30–2:15 | Reconciliation, dedupe, coverage, remaining synthetic files | Rules 9–15, metrics with breakdowns | Analysis screen + breakdown drawer |
| 2:15–2:45 | Flags | eval/score.py, fix misclassifications | Review screen, charts |
| 2:45–3:00 | **Everyone:** full demo run from empty DB, fix what breaks | | |

**Integration contract:** P1 outputs `list[TransactionIn]` + `StatementIn`; P2 consumes from DB only. Agree on `models.py` in the first 15 minutes and don't touch it without telling the others.

---

## 11. Demo script (rehearse it)

1. Upload all files at once → show scanned page failure and the broken balance row highlighted.
2. Coverage strip shows July missing; overlapping June shows duplicates removed.
3. Open salary: one recurring cluster despite the name change.
4. Open estimated income → ₹50k transfers listed under *excluded* with "matched to credit in XXXX5678".
5. Reclassify a transfer as salary → income jumps, original classification still visible in history. Undo it.
6. Self-employed account: median based income vs naive max month.
7. Review queue: cash deposit + round figure spike, labelled "needs review".
8. Accuracy score vs ground truth.
