"""
Configurable thresholds for behavioural analysis, red-flag metrics, and the
borrower-assessment rule engine (handoff Phases 3-5).

Every value here is an ILLUSTRATIVE STARTING POINT supplied by the handoff
or chosen for this build, NOT an official or universal underwriting
standard (handoff: "These are starting assumptions, not official or
universal underwriting standards"). See ASSUMPTIONS.md A-006 for why this
lives in a config module rather than a database/admin UI, and DECISIONS.md
for the rule-version this file corresponds to.

To change a threshold: edit the value and bump THRESHOLDS_VERSION. Every
RuleEvaluation row records which version produced it, so changing a number
here does not silently rewrite historical audit records.
"""
from decimal import Decimal

THRESHOLDS_VERSION = "2026-10-31.1"

# ---- Individual: FOIR / DTI bands ----
FOIR_LOWER_BURDEN_MAX = Decimal("40")      # <=40% lower burden
FOIR_ELEVATED_MAX = Decimal("55")          # 40-55% elevated; >55% higher burden

# ---- SME: DSCR bands ----
DSCR_SHORTFALL_MAX = Decimal("1.0")        # <1.0 possible debt-service shortfall
DSCR_STRONG_MIN = Decimal("1.5")           # >=1.5 stronger coverage

# ---- SME: CC/OD utilization ----
CC_OD_UTILIZATION_PRESSURE_MIN = Decimal("90")  # above 90% may indicate liquidity pressure

# ---- SME: customer concentration (configurable, no illustrative number given) ----
CONCENTRATION_TOP1_ELEVATED_MIN = Decimal("40")   # top-1 customer > 40% of verified inflow
CONCENTRATION_TOP3_ELEVATED_MIN = Decimal("70")   # top-3 customers > 70% of verified inflow

# ---- Low-balance / EOD balance stress ----
# "A possible initial threshold is 5% of average monthly balance" - computed
# dynamically per account in redflags.py; this is the floor used when NAMB
# itself cannot be computed (e.g. first statement, no balance history).
EOD_STRESS_FALLBACK_THRESHOLD = Decimal("1000")
EOD_STRESS_PERCENT_OF_NAMB = Decimal("0.05")
EOD_STRESS_CONSECUTIVE_DAYS_WARN = 3

# ---- Round-tripping / circular flow detection window ----
ROUND_TRIP_WINDOW_HOURS_MIN = 24
ROUND_TRIP_WINDOW_HOURS_MAX = 48
ROUND_TRIP_AMOUNT_TOLERANCE_PCT = Decimal("0.02")  # "near-matching amounts"

# ---- Salary-to-Obligation Cleansing Cycle ----
LOW_BALANCE_THRESHOLD_FOR_CLEANSING_CYCLE = Decimal("1000")  # configurable floor

# ---- Behavioural deviation detection ----
DEVIATION_WARN_PCT = Decimal("30")    # % deviation from historical median to flag
DEVIATION_HIGH_PCT = Decimal("60")
MIN_HISTORY_MONTHS_FOR_DEVIATION = 2  # below this, label results provisional

# ---- AI Reviewer escalation policy (ASSUMPTIONS.md A-008, provisional/off by default) ----
AI_AUTO_RESOLVE_ENABLED = False
AI_AUTO_RESOLVE_MIN_CONFIDENCE = 0.75
