"""
Planted scenarios for the synthetic demo data (BUILD_PLAN.md section 7).
Each ledger row is (date, description, debit, credit, expected_category).
Running balances are computed from an opening balance in generate.py, not
hand-typed here, so every file stays internally consistent.

Account A: Lotus Bank savings (Layout A, table-based PDF)
Account B: Meridian Co-operative Bank current (Layout B, text-based PDF)
Both accounts belong to the same holder, so Account A's transfer-out and
Account B's transfer-in should pair up as INTERNAL_TRANSFER (rule XFER_PAIR).
"""
from datetime import date
from decimal import Decimal as D

HOLDER_NAME = "RAHUL SHARMA"

ACCOUNT_A = {
    "holder_name": HOLDER_NAME,
    "account_number": "1234567801",
    "bank_name": "Lotus Bank",
}

ACCOUNT_B = {
    "holder_name": HOLDER_NAME,
    "account_number": "9876505678",
    "bank_name": "Meridian Co-operative Bank",
}

# ---- Account A: Lotus Bank savings, continuous Apr-Aug ledger ----
# Split into two overlapping PDFs: apr_jun (Apr-Jun) and jun_aug (Jun-Aug),
# so June rows appear in both files (duplicate-detection scenario).
BANKA_OPENING = D("80000.00")
BANKA_LEDGER = [
    (date(2026, 4, 2), "ACME TECH PVT LTD SAL APR", None, D("45000.00"), "SALARY"),
    (date(2026, 4, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 4, 5), "AMAZON.IN ORDER 4521", D("2500.00"), None, "OTHER_EXPENSE"),
    (date(2026, 4, 10), "AMAZON REFUND ORDER 4521", None, D("2500.00"), "REFUND"),
    (date(2026, 4, 15), "ATM CASH WDL", D("3000.00"), None, "CASH_WITHDRAWAL"),
    (date(2026, 4, 20), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    (date(2026, 5, 2), "ACME TECH PVT LTD SAL MAY", None, D("45000.00"), "SALARY"),
    (date(2026, 5, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 5, 12), "SWIGGY ORDER 8812", D("650.00"), None, "OTHER_EXPENSE"),
    (date(2026, 5, 18), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    # June: payroll provider renamed mid-year - cluster must survive the rename
    (date(2026, 6, 2), "RAZORPAYX PAYROLL ACME", None, D("45000.00"), "SALARY"),
    (date(2026, 6, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 6, 14), "SWIGGY ORDER 9921", D("720.00"), None, "OTHER_EXPENSE"),
    (date(2026, 6, 20), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    (date(2026, 7, 2), "RAZORPAYX PAYROLL ACME", None, D("45000.00"), "SALARY"),
    (date(2026, 7, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 7, 14), "SWIGGY ORDER 1092", D("680.00"), None, "OTHER_EXPENSE"),
    (date(2026, 7, 20), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    (date(2026, 8, 2), "RAZORPAYX PAYROLL ACME", None, D("45000.00"), "SALARY"),
    (date(2026, 8, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 8, 14), "SWIGGY ORDER 2217", D("700.00"), None, "OTHER_EXPENSE"),
    (date(2026, 8, 20), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    # September keeps the running six-month story and covers the reversal + bank-charge rules
    (date(2026, 9, 2), "RAZORPAYX PAYROLL ACME", None, D("45000.00"), "SALARY"),
    (date(2026, 9, 3), "NEFT TO OWN A/C MERIDIAN 5678", D("50000.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 9, 10), "REVERSAL OF AMAZON ORDER 4521", None, D("2500.00"), "REVERSAL"),
    (date(2026, 9, 14), "SWIGGY ORDER 3328", D("680.00"), None, "OTHER_EXPENSE"),
    (date(2026, 9, 20), "BESCOM ELECTRICITY BILL", D("1450.00"), None, "UTILITIES"),
    (date(2026, 9, 23), "GST ON BANK CHARGES", D("125.00"), None, "BANK_CHARGES"),
]
BANKA_FILE1_RANGE = (date(2026, 4, 1), date(2026, 9, 30))   # bankA_savings_apr_sep.pdf
BANKA_FILE2_RANGE = (date(2026, 6, 1), date(2026, 9, 30))   # bankA_savings_jun_sep.pdf (overlaps June)

# ---- Account B: Meridian current, Apr-Jun then Aug-Sep (July has no statement -> missing) ----
BANKB_OPENING = D("30000.00")
BANKB_LEDGER = [
    (date(2026, 4, 3), "NEFT CR FROM RAHUL SHARMA LOTUS 1801", None, D("50000.00"), "INTERNAL_TRANSFER"),
    (date(2026, 4, 8), "UPI CR FROM BRIGHT RETAIL", None, D("12500.00"), "BUSINESS_RECEIPT"),
    (date(2026, 4, 16), "UPI CR FROM NOVA TRADERS", None, D("9800.00"), "BUSINESS_RECEIPT"),
    (date(2026, 4, 22), "EMI PAYMENT LOAN8842", D("18450.00"), None, "LOAN_EMI"),
    # GOLDEN EXPORTS appears only once in this ledger - single/new
    # counterparty, correctly unverified rather than confident BUSINESS_RECEIPT
    # (handoff: "A new sender is not inherently suspicious... use
    # POSSIBLE_BUSINESS_RECEIPT... when purpose is unclear").
    (date(2026, 4, 28), "UPI CR FROM GOLDEN EXPORTS", None, D("13400.00"), "POSSIBLE_BUSINESS_RECEIPT"),
    (date(2026, 5, 3), "NEFT CR FROM RAHUL SHARMA LOTUS 1801", None, D("50000.00"), "INTERNAL_TRANSFER"),
    (date(2026, 5, 9), "NEFT CR FROM ZEN ENTERPRISES", None, D("21000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 5, 14), "UPI CR FROM BRIGHT RETAIL", None, D("7600.00"), "BUSINESS_RECEIPT"),
    (date(2026, 5, 22), "EMI PAYMENT LOAN8842", D("18450.00"), None, "LOAN_EMI"),
    (date(2026, 5, 28), "UPI CR FROM METRO SUPPLIES", None, D("9100.00"), "POSSIBLE_BUSINESS_RECEIPT"),  # single occurrence
    (date(2026, 6, 3), "NEFT CR FROM RAHUL SHARMA LOTUS 1801", None, D("50000.00"), "INTERNAL_TRANSFER"),
    (date(2026, 6, 11), "UPI CR FROM QUICKCART SOLUTIONS", None, D("15300.00"), "BUSINESS_RECEIPT"),
    (date(2026, 6, 19), "UPI CR FROM NOVA TRADERS", None, D("6400.00"), "BUSINESS_RECEIPT"),
    (date(2026, 6, 22), "EMI PAYMENT LOAN8842", D("18450.00"), None, "LOAN_EMI"),
    # July: deliberately no transactions / no statement -> coverage shows "missing"
    (date(2026, 8, 3), "NEFT CR FROM RAHUL SHARMA LOTUS 1801", None, D("50000.00"), "INTERNAL_TRANSFER"),
    (date(2026, 8, 10), "LOAN DISBURSAL HOME LOAN", None, D("500000.00"), "LOAN_DISBURSEMENT"),
    (date(2026, 8, 18), "UPI CR FROM ZEN ENTERPRISES", None, D("11200.00"), "BUSINESS_RECEIPT"),
    (date(2026, 8, 22), "EMI PAYMENT LOAN8842", D("18450.00"), None, "LOAN_EMI"),
    (date(2026, 8, 27), "UPI CR FROM SILVER MART", None, D("30000.00"), "POSSIBLE_BUSINESS_RECEIPT"),  # single occurrence
    (date(2026, 9, 5), "UPI CR FROM TRIVEDI AND SONS", None, D("8200.00"), "POSSIBLE_BUSINESS_RECEIPT"),  # single occurrence
    (date(2026, 9, 9), "NACH RTN INSUFFICIENT FUNDS", D("590.00"), None, "RETURNED_PAYMENT"),
    (date(2026, 9, 14), "CASH DEPOSIT BRANCH", None, D("95000.00"), "CASH_DEPOSIT"),
    (date(2026, 9, 20), "UPI CR FROM QUICKCART SOLUTIONS", None, D("40000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 9, 22), "EMI PAYMENT LOAN8842", D("18450.00"), None, "LOAN_EMI"),
    (date(2026, 9, 25), "UPI CR FROM BRIGHT RETAIL", None, D("20000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 9, 28), "GST ON BANK CHARGES", D("150.00"), None, "BANK_CHARGES"),
]
BANKB_FILE1_RANGE = (date(2026, 4, 1), date(2026, 6, 30))   # bankB_current_apr_jun.pdf
BANKB_FILE2_RANGE = (date(2026, 8, 1), date(2026, 9, 30))   # bankB_current_aug_sep.pdf

# ---- bankA_broken_balance.pdf: one row's printed balance off by Rs.1000 ----
BROKEN_OPENING = D("40000.00")
BROKEN_LEDGER = [
    # Both credits below are single-occurrence counterparties in this short
    # ledger - correctly unverified (POSSIBLE_BUSINESS_RECEIPT) rather than
    # confident BUSINESS_RECEIPT, same reasoning as the GOLDEN EXPORTS /
    # METRO SUPPLIES rows above.
    (date(2026, 10, 2), "CONSULTING INCOME UPI", None, D("15000.00"), "POSSIBLE_BUSINESS_RECEIPT"),
    (date(2026, 10, 10), "RENT PAYMENT OCT", D("5000.00"), None, "RENT"),
    (date(2026, 10, 15), "JIO RECHARGE", D("1200.00"), None, "UTILITIES"),
    (date(2026, 10, 25), "UPI CR FROM CLIENT XYZ", None, D("8000.00"), "POSSIBLE_BUSINESS_RECEIPT"),
]
BROKEN_ROW_INDEX = 3  # 1-indexed transaction row where the balance is corrupted (JIO RECHARGE row)
BROKEN_OFFSET = D("1000.00")

# ---- Structured files: different column names, small sets ----
CARD_SPEND_ROWS = [
    # (Transaction Date, Merchant, Amount Debited, Amount Credited)
    (date(2026, 7, 2), "ZOMATO ONLINE ORDER", D("540.00"), None, "OTHER_EXPENSE"),
    (date(2026, 7, 6), "RELIANCE DIGITAL", D("12999.00"), None, "OTHER_EXPENSE"),
    (date(2026, 7, 9), "CASHBACK ZOMATO ONLINE ORDER", None, D("54.00"), "REFUND"),
    (date(2026, 7, 15), "NETFLIX SUBSCRIPTION", D("649.00"), None, "OTHER_EXPENSE"),
]

WALLET_JSON_ROWS = [
    # (txn date, narration, debit amount, credit amount)
    (date(2026, 7, 3), "ADDED MONEY VIA UPI", None, D("5000.00"), "POSSIBLE_BUSINESS_RECEIPT"),  # single occurrence
    (date(2026, 7, 8), "PAID TO METRO SUPPLIES", D("2200.00"), None, "OTHER_EXPENSE"),
    (date(2026, 7, 19), "AIRTEL RECHARGE", D("399.00"), None, "UTILITIES"),
]

LEDGER_XLSX_ROWS = [
    # (value date, particulars, withdrawal amt, deposit amt)
    (date(2026, 7, 4), "RENT RECEIVED TENANT", None, D("18000.00"), "RENT"),
    (date(2026, 7, 11), "CC PAYMENT CREDIT CARD", D("22000.00"), None, "CARD_PAYMENT"),
    (date(2026, 7, 21), "INT.PD SAVINGS", None, D("312.50"), "INTEREST"),
]

# ---- SME account: high customer concentration, supplier payments, a
# possible-circular-flow pair, and an NSF bounce (handoff Phase 8: "SME
# with recurring customers and supplier payments", "SME with high customer
# concentration", "Rapid inflow/outflow and possible circular flows"). ----
SME_ACCOUNT = {
    "holder_name": "ACME TRADERS",
    "account_number": "5566778899",
    "bank_name": "Lotus Bank",
}
SME_OPENING = D("100000.00")
SME_LEDGER = [
    # MEGAMART and REGULAR BUYER both recur (>=2 credits each) so both
    # count as verified BUSINESS_RECEIPT; irregular day-of-month/gaps keep
    # find_salary_clusters() from mistaking either for a payroll cluster
    # (see ASSUMPTIONS.md A-011). Rows are kept in strict chronological
    # order (required for row-level balance reconciliation to hold).
    (date(2026, 4, 5), "UPI CR FROM MEGAMART RETAIL", None, D("300000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 4, 9), "UPI CR FROM REGULAR BUYER CO", None, D("15000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 4, 15), "SUPPLIER PAYMENT TEXTILE HUB", D("80000.00"), None, "OTHER_EXPENSE"),
    (date(2026, 4, 20), "EMI PAYMENT LOAN9911", D("25000.00"), None, "LOAN_EMI"),
    # Possible circular flow: outgoing NEFT followed within 24h by an
    # inbound credit from the same counterparty, near-matching amount.
    (date(2026, 4, 25), "NEFT TO VENDOR RAPIDSHIP", D("50000.00"), None, "OTHER_EXPENSE"),
    (date(2026, 4, 26), "NEFT FROM VENDOR RAPIDSHIP", None, D("49500.00"), "POSSIBLE_BUSINESS_RECEIPT"),
    (date(2026, 5, 10), "SUPPLIER PAYMENT TEXTILE HUB", D("82000.00"), None, "OTHER_EXPENSE"),
    (date(2026, 5, 15), "EMI PAYMENT LOAN9911", D("25000.00"), None, "LOAN_EMI"),
    (date(2026, 5, 20), "UPI CR FROM MEGAMART RETAIL", None, D("310000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 5, 24), "UPI CR FROM REGULAR BUYER CO", None, D("12000.00"), "BUSINESS_RECEIPT"),
    # NSF / bounce event (handoff red-flag metric).
    (date(2026, 5, 28), "NACH RTN INSUFFICIENT FUNDS", D("500.00"), None, "RETURNED_PAYMENT"),
    (date(2026, 6, 2), "UPI CR FROM MEGAMART RETAIL", None, D("295000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 6, 6), "UPI CR FROM REGULAR BUYER CO", None, D("18000.00"), "BUSINESS_RECEIPT"),
    (date(2026, 6, 15), "SUPPLIER PAYMENT TEXTILE HUB", D("79000.00"), None, "OTHER_EXPENSE"),
    (date(2026, 6, 20), "EMI PAYMENT LOAN9911", D("25000.00"), None, "LOAN_EMI"),
]

# ---- UAE / Oman-style example account (foreign-currency demo) ----
UAE_ACCOUNT = {
    "holder_name": "MOHAMMED ALI",
    "account_number": "OM123456789",
    "bank_name": "Bank Muscat",
    "currency": "OMR",
}

UAE_OPENING = D("3500.00")
UAE_LEDGER = [
    (date(2026, 4, 2), "SALARY CREDIT APR", None, D("1250.00"), "SALARY"),
    (date(2026, 4, 5), "NEFT TO OWN A/C ABU DHABI", D("800.00"), None, "INTERNAL_TRANSFER"),
    (date(2026, 4, 16), "OMR PAYMENTS - MUSCAT CITY MALL", D("210.00"), None, "OTHER_EXPENSE"),
    (date(2026, 4, 24), "GAS BILL MUSCAT", D("95.00"), None, "UTILITIES"),
    (date(2026, 5, 2), "SALARY CREDIT MAY", None, D("1250.00"), "SALARY"),
    (date(2026, 5, 5), "CASH DEPOSIT BRANCH", None, D("500.00"), "CASH_DEPOSIT"),
    (date(2026, 5, 9), "ATM CASH WITHDRAWAL", D("150.00"), None, "CASH_WITHDRAWAL"),
    (date(2026, 6, 2), "SALARY CREDIT JUN", None, D("1250.00"), "SALARY"),
    (date(2026, 6, 10), "RENT PAYMENT", D("550.00"), None, "RENT"),
    (date(2026, 6, 18), "MOBILE RECHARGE OMAN", D("28.00"), None, "UTILITIES"),
    (date(2026, 7, 2), "SALARY CREDIT JUL", None, D("1250.00"), "SALARY"),
    (date(2026, 7, 12), "UPI CR FROM MIDDLE EAST RETAIL", None, D("1200.00"), "BUSINESS_RECEIPT"),
    (date(2026, 7, 18), "EMI PAYMENT LOAN220", D("180.00"), None, "LOAN_EMI"),
    (date(2026, 8, 2), "SALARY CREDIT AUG", None, D("1250.00"), "SALARY"),
    (date(2026, 8, 11), "REFUND - AIRLINE BOOKING", None, D("120.00"), "REFUND"),
    (date(2026, 8, 20), "GST ON BANK CHARGES", D("10.00"), None, "BANK_CHARGES"),
    (date(2026, 9, 2), "SALARY CREDIT SEP", None, D("1250.00"), "SALARY"),
    (date(2026, 9, 18), "AUTO DEBIT LOAN", D("180.00"), None, "LOAN_EMI"),
]
UAE_FILE_RANGE = (date(2026, 4, 1), date(2026, 9, 30))

AED_ACCOUNT = {
    "holder_name": "FATIMA HASSAN",
    "account_number": "AE987654321",
    "bank_name": "Emirates NBD",
    "currency": "AED",
}

AED_OPENING = D("19000.00")
AED_LEDGER = [
    (date(2026, 4, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4200.00"), "BUSINESS_RECEIPT"),
    (date(2026, 4, 8), "DU BILL PAYMENT", D("320.00"), None, "UTILITIES"),
    (date(2026, 4, 14), "HOME RENT", D("11000.00"), None, "RENT"),
    (date(2026, 5, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4300.00"), "BUSINESS_RECEIPT"),
    (date(2026, 5, 22), "CASH DEPOSIT BRANCH", None, D("2500.00"), "CASH_DEPOSIT"),
    (date(2026, 6, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4200.00"), "BUSINESS_RECEIPT"),
    (date(2026, 6, 12), "CARD PAYMENT SHARJAH MALL", D("680.00"), None, "CARD_PAYMENT"),
    (date(2026, 7, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4400.00"), "BUSINESS_RECEIPT"),
    (date(2026, 7, 18), "EMI PAYMENT LOAN875", D("1280.00"), None, "LOAN_EMI"),
    (date(2026, 8, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4500.00"), "BUSINESS_RECEIPT"),
    (date(2026, 8, 19), "REFUND - WEATHER APP", None, D("95.00"), "REFUND"),
    (date(2026, 9, 3), "CLIENT PAYMENT - DUBAI MALL", None, D("4700.00"), "BUSINESS_RECEIPT"),
    (date(2026, 9, 22), "BANK CHARGES", D("35.00"), None, "BANK_CHARGES"),
]
AED_FILE_RANGE = (date(2026, 4, 1), date(2026, 9, 30))

# ============================================================
# OMR MASTER DATASET — Bank Muscat savings (Layout A PDF)
# Holder: YUSUF AL-RASHIDI
# 6-month comprehensive ledger covering every transaction category
# the pipeline supports, plus planted flag scenarios:
#   • NSF / returned payment (July)
#   • Possible round-trip pair (August, AL-MUBARAK TRADING)
#   • EOD balance stress (July — high summer utility + NSF)
#   • INTERNAL_TRANSFER pairs with NBO account below
#   • Two POSSIBLE_BUSINESS_RECEIPT (single-occurrence consulting)
#   • INTEREST and BANK_CHARGES
# ============================================================

OMR_MASTER_ACCOUNT = {
    "holder_name": "YUSUF AL-RASHIDI",
    "account_number": "OM0123456780",
    "bank_name": "Bank Muscat",
    "currency": "OMR",
}

OMR_MASTER_OPENING = D("2800.000")

OMR_MASTER_LEDGER = [
    # ── April ──
    (date(2026, 4, 1),  "SALARY CREDIT - OMAN OIL COMPANY APR",     None,           D("1850.000"), "SALARY"),
    (date(2026, 4, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 4, 5),  "MZEC ELECTRICITY BILL APR",                 D("44.500"),    None,          "UTILITIES"),
    (date(2026, 4, 7),  "OMANTEL POSTPAID APR",                      D("28.000"),    None,          "UTILITIES"),
    (date(2026, 4, 10), "LULU HYPERMARKET MUSCAT CITY CENTRE",       D("125.300"),   None,          "OTHER_EXPENSE"),
    (date(2026, 4, 15), "TRANSFER TO OWN A/C NBO 6504",              D("500.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 4, 18), "CARREFOUR OMAN ONLINE",                     D("87.500"),    None,          "OTHER_EXPENSE"),
    (date(2026, 4, 22), "ATM CASH WITHDRAWAL RUWI BRANCH",           D("200.000"),   None,          "CASH_WITHDRAWAL"),
    (date(2026, 4, 28), "REFUND - NOON.COM ORDER OM4412",            None,           D("45.000"),   "REFUND"),
    # ── May ──
    (date(2026, 5, 1),  "SALARY CREDIT - OMAN OIL COMPANY MAY",     None,           D("1850.000"), "SALARY"),
    (date(2026, 5, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 5, 5),  "MZEC ELECTRICITY BILL MAY",                 D("52.000"),    None,          "UTILITIES"),
    (date(2026, 5, 7),  "OOREDOO MOBILE POSTPAID MAY",               D("22.000"),    None,          "UTILITIES"),
    (date(2026, 5, 9),  "CAR LOAN EMI OMAN AUTO 1144",               D("142.500"),   None,          "LOAN_EMI"),
    (date(2026, 5, 12), "AL MEERA CONSUMER GOODS MUSCAT",            D("94.200"),    None,          "OTHER_EXPENSE"),
    (date(2026, 5, 15), "TRANSFER TO OWN A/C NBO 6504",              D("500.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 5, 20), "CASH DEPOSIT MATRAH BRANCH",                None,           D("300.000"),  "CASH_DEPOSIT"),
    (date(2026, 5, 25), "CONSULTING PAYMENT - TECHSOL OM",           None,           D("600.000"),  "POSSIBLE_BUSINESS_RECEIPT"),
    # ── June ──
    (date(2026, 6, 1),  "SALARY CREDIT - OMAN OIL COMPANY JUN",     None,           D("1850.000"), "SALARY"),
    (date(2026, 6, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 6, 5),  "MZEC ELECTRICITY BILL JUN",                 D("68.500"),    None,          "UTILITIES"),
    (date(2026, 6, 8),  "MARKAZ AL BAHJA SHOPPING CENTRE",           D("175.000"),   None,          "OTHER_EXPENSE"),
    (date(2026, 6, 9),  "CAR LOAN EMI OMAN AUTO 1144",               D("142.500"),   None,          "LOAN_EMI"),
    (date(2026, 6, 15), "TRANSFER TO OWN A/C NBO 6504",              D("500.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 6, 20), "BANK SERVICE CHARGE Q2",                    D("5.000"),     None,          "BANK_CHARGES"),
    (date(2026, 6, 25), "INTEREST CREDIT SAVINGS Q2",                None,           D("14.350"),   "INTEREST"),
    # ── July — cash stress: peak summer utility + NSF bounce ──
    (date(2026, 7, 1),  "SALARY CREDIT - OMAN OIL COMPANY JUL",     None,           D("1850.000"), "SALARY"),
    (date(2026, 7, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 7, 5),  "MZEC ELECTRICITY BILL JUL",                 D("95.000"),    None,          "UTILITIES"),
    (date(2026, 7, 8),  "NACH RTN INSUFFICIENT FUNDS",               D("28.000"),    None,          "RETURNED_PAYMENT"),
    (date(2026, 7, 9),  "CAR LOAN EMI OMAN AUTO 1144",               D("142.500"),   None,          "LOAN_EMI"),
    (date(2026, 7, 12), "LULU HYPERMARKET QURUM",                    D("138.700"),   None,          "OTHER_EXPENSE"),
    (date(2026, 7, 15), "TRANSFER TO OWN A/C NBO 6504",              D("400.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 7, 18), "ATM CASH WITHDRAWAL QURUM ATM",             D("100.000"),   None,          "CASH_WITHDRAWAL"),
    (date(2026, 7, 22), "CONSULTING PAYMENT - TECHSOL OM",           None,           D("600.000"),  "POSSIBLE_BUSINESS_RECEIPT"),
    # ── August — possible round-trip pair (AL-MUBARAK TRADING) ──
    (date(2026, 8, 1),  "SALARY CREDIT - OMAN OIL COMPANY AUG",     None,           D("1850.000"), "SALARY"),
    (date(2026, 8, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 8, 5),  "MZEC ELECTRICITY BILL AUG",                 D("88.000"),    None,          "UTILITIES"),
    (date(2026, 8, 9),  "CAR LOAN EMI OMAN AUTO 1144",               D("142.500"),   None,          "LOAN_EMI"),
    (date(2026, 8, 12), "NEFT TO AL-MUBARAK TRADING LLC",            D("800.000"),   None,          "OTHER_EXPENSE"),
    (date(2026, 8, 13), "NEFT FROM AL-MUBARAK TRADING LLC",          None,           D("790.000"),  "POSSIBLE_BUSINESS_RECEIPT"),
    (date(2026, 8, 15), "TRANSFER TO OWN A/C NBO 6504",              D("500.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 8, 22), "CARD PAYMENT OMAN AIR BOOKING",             D("245.000"),   None,          "CARD_PAYMENT"),
    # ── September ──
    (date(2026, 9, 1),  "SALARY CREDIT - OMAN OIL COMPANY SEP",     None,           D("1850.000"), "SALARY"),
    (date(2026, 9, 3),  "HOME LOAN EMI BFIN2023",                    D("385.000"),   None,          "LOAN_EMI"),
    (date(2026, 9, 5),  "MZEC ELECTRICITY BILL SEP",                 D("72.000"),    None,          "UTILITIES"),
    (date(2026, 9, 8),  "CAR LOAN EMI OMAN AUTO 1144",               D("142.500"),   None,          "LOAN_EMI"),
    (date(2026, 9, 10), "CONSULTING INCOME - MAZOON DIGITAL",        None,           D("750.000"),  "POSSIBLE_BUSINESS_RECEIPT"),
    (date(2026, 9, 15), "TRANSFER TO OWN A/C NBO 6504",              D("500.000"),   None,          "INTERNAL_TRANSFER"),
    (date(2026, 9, 18), "CARREFOUR OMAN HYPERMARKET QURUM",          D("112.600"),   None,          "OTHER_EXPENSE"),
    (date(2026, 9, 22), "OMANTEL POSTPAID SEP",                      D("28.000"),    None,          "UTILITIES"),
    (date(2026, 9, 28), "BANK SERVICE CHARGES Q3",                   D("8.500"),     None,          "BANK_CHARGES"),
]
OMR_MASTER_FILE_RANGE = (date(2026, 4, 1), date(2026, 9, 30))

# ============================================================
# OMR SECOND ACCOUNT — National Bank of Oman current (CSV)
# Paired with OMR_MASTER_ACCOUNT via internal transfers.
# Demonstrates cross-account pairing and XFER_PAIR rule.
# ============================================================

OMR_NBO_ACCOUNT = {
    "holder_name": "YUSUF AL-RASHIDI",
    "account_number": "OM0098765040",
    "bank_name": "National Bank of Oman",
    "currency": "OMR",
}

OMR_NBO_OPENING = D("1200.000")

OMR_NBO_LEDGER = [
    (date(2026, 4, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("500.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 4, 22), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 4, 26), "SPINNEYS MUSCAT GROCERY",             D("88.750"),   None,          "OTHER_EXPENSE"),
    (date(2026, 5, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("500.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 5, 20), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 5, 27), "PHARMACARE MUSCAT",                   D("34.500"),   None,          "OTHER_EXPENSE"),
    (date(2026, 6, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("500.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 6, 20), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 6, 25), "INTEREST CREDIT Q2",                  None,          D("6.120"),    "INTEREST"),
    (date(2026, 7, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("400.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 7, 20), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 7, 28), "ATM CASH WITHDRAWAL NBO RUWI",        D("150.000"),  None,          "CASH_WITHDRAWAL"),
    (date(2026, 8, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("500.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 8, 20), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 8, 24), "LULU EXPRESS BAUSHER",                D("62.300"),   None,          "OTHER_EXPENSE"),
    (date(2026, 9, 15), "TFR FROM OWN A/C BANK MUSCAT 6780",  None,          D("500.000"),  "INTERNAL_TRANSFER"),
    (date(2026, 9, 20), "RENT PAYMENT BAUSHER FLAT",           D("300.000"),  None,          "RENT"),
    (date(2026, 9, 27), "BANK CHARGES Q3",                     D("5.000"),    None,          "BANK_CHARGES"),
]
OMR_NBO_FILE_RANGE = (date(2026, 4, 1), date(2026, 9, 30))
