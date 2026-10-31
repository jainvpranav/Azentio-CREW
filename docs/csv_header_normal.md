Handoff: International CSV Header Normalization
Goal
Implement non-destructive CSV header normalization for international bank statements. Map recognized columns to the internal transaction schema while preserving every original header and value. Never lose custom, regional, or institution-specific data.
Requirements

1. Header mapping
   Use an extensible, configurable alias dictionary. Initial mappings:
   Internal key Example aliases
   transaction_date date, posting date, txn date, transaction date, fecha, data
   description description, narration, memo, details, particulars, remarks, historique
   amount amount, transaction amount, txn amount, importe, localized generic amount labels
   debit debit, withdrawal(s), outflow, paid out, localized debit/withdrawal labels
   credit credit, deposit(s), inflow, paid in, localized credit/deposit labels
   balance balance, running balance, closing balance, available balance, solde, localized balance labels

Support new languages, banks, and institution-specific aliases without changing the core parser. 2. Header normalization and matching
Before matching:

- Trim whitespace; normalize case and repeated spaces.
- Normalize underscores, hyphens, and common punctuation consistently.
- Support Unicode and accented characters.
- Match cleaned headers against configured aliases first; use fuzzy matching only above a safe confidence threshold.
- Return no match for low-confidence or ambiguous headers. Do not guess.
  Retain the exact original header alongside any normalized key.

3. Row preservation
   For every row:
4. Read original headers and values.
5. Populate recognized internal fields.
6. Preserve every original header-value pair.
7. Put unmapped fields (including fields such as Branch Code, Reference ID, and Channel) in transaction-level custom_metadata.
8. Keep source values available to financial calculations, running-balance checks, audit trails, and review dashboards.
9. Record unresolved and ambiguous mappings; never silently discard or choose between conflicting values.
   Logical output example (implementation names/types may differ if both normalized and source data remain available):
   {
   "transaction_date": "2026-10-30",
   "description": "ATM Withdrawal",
   "debit": "2500.00",
   "credit": null,
   "balance": "47500.00",
   "custom_metadata": {
   "Branch Code": "BLR001",
   "Reference ID": "REF987654321",
   "Channel": "ATM"
   },
   "source_data": {
   "Posting Date": "2026-10-30",
   "Narration": "ATM Withdrawal",
   "Withdrawal": "2500.00",
   "Running Balance": "47500.00",
   "Branch Code": "BLR001",
   "Reference ID": "REF987654321",
   "Channel": "ATM"
   }
   }
10. Duplicate and ambiguous mappings

- If multiple source headers map to one internal key, preserve all values; never overwrite by column order.
- Use explicit, documented precedence only when the authoritative source is determinable.
- Otherwise mark the mapping ambiguous for review.
- Preserve empty, unknown, and institution-specific columns according to the ingestion retention policy.
  Deliverables
  A. Reusable normalizer
  Implement:
  def normalize_header(raw_header: str) -> str | None:
  """Return a confidently matched internal key; otherwise None."""
  It must clean the header, use configurable aliases, support Unicode/international terms, apply fuzzy-match confidence thresholds, and return None for unknown or ambiguous headers. The caller must retain the original header.
  B. CSV ingestion integration
- Retain original headers and row data.
- Apply normalize_header to each header and populate core fields.
- Store all unmapped header-value pairs in custom_metadata.
- Preserve duplicate/ambiguous mappings without data loss.
- Return a consistent transaction structure for downstream use.
  C. Downstream availability
  Expose normalized and preserved data to:
- Financial calculations and running-balance validation.
- Multi-currency validation, retaining each amount's currency identifier.
- Fraud/anomaly rules.
- Database persistence and audit trails.
- Frontend review dashboards.
  Non-negotiable invariants

1. No data loss: never discard or silently overwrite source columns or values.
2. Safe matching: uncertain or ambiguous headers remain unresolved, not guessed.
3. Traceability: retain original headers and row values.
4. Extensibility: aliases remain configurable.
5.
6. Stable output: provide predictable normalized fields without removing source data.
