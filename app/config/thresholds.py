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
import json
import os

THRESHOLDS_VERSION = "2026-10-31.1"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "runtime_rules.json")

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

RULE_CONFIG = {
    "FOIR_LOWER_BURDEN_MAX": {"label": "FOIR lower burden max (%)", "kind": "number", "step": "0.1", "min": 0, "max": 100},
    "FOIR_ELEVATED_MAX": {"label": "FOIR elevated max (%)", "kind": "number", "step": "0.1", "min": 0, "max": 100},
    "DSCR_SHORTFALL_MAX": {"label": "DSCR shortfall max", "kind": "number", "step": "0.1", "min": 0, "max": 5},
    "CC_OD_UTILIZATION_PRESSURE_MIN": {"label": "CC/OD utilization pressure (%)", "kind": "number", "step": "1", "min": 0, "max": 100},
    "LOW_BALANCE_THRESHOLD_FOR_CLEANSING_CYCLE": {"label": "Low-balance threshold (₹)", "kind": "number", "step": "100", "min": 0},
    "EOD_STRESS_FALLBACK_THRESHOLD": {"label": "EOD stress fallback threshold (₹)", "kind": "number", "step": "100", "min": 0},
    "AI_AUTO_RESOLVE_ENABLED": {"label": "AI auto-resolve enabled", "kind": "checkbox"},
    "AI_AUTO_RESOLVE_MIN_CONFIDENCE": {"label": "AI min confidence", "kind": "number", "step": "0.05", "min": 0, "max": 1},
}


def _default_rule_values():
    return {
        key: _serialize_value(globals()[key])
        for key in RULE_CONFIG
    }


def _serialize_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _coerce_rule_value(key, raw_value):
    current = globals().get(key)
    if isinstance(current, Decimal):
        return Decimal(str(raw_value))
    if isinstance(current, bool):
        return bool(raw_value)
    if isinstance(current, int):
        return int(raw_value)
    if isinstance(current, float):
        return float(raw_value)
    return raw_value


def load_runtime_rules():
    if not os.path.exists(CONFIG_PATH):
        return _default_rule_values()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            overrides = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return _default_rule_values()

    if not isinstance(overrides, dict):
        return _default_rule_values()

    merged = _default_rule_values()
    merged.update({key: value for key, value in overrides.items() if key in RULE_CONFIG})
    for key, value in merged.items():
        if key in globals():
            globals()[key] = _coerce_rule_value(key, value)
    return merged


def save_runtime_rules(updates):
    if not isinstance(updates, dict):
        raise ValueError("Rule updates must be a dictionary.")

    merged = _default_rule_values()
    for key in list(RULE_CONFIG.keys()):
        if key in updates:
            merged[key] = updates[key]

    for key, value in merged.items():
        if key in globals():
            globals()[key] = _coerce_rule_value(key, value)

    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)

    return merged


def get_rule_rows():
    values = {
        key: _serialize_value(globals().get(key, default))
        for key, default in _default_rule_values().items()
    }
    rows = []
    for key, meta in RULE_CONFIG.items():
        rows.append({
            "key": key,
            "label": meta["label"],
            "kind": meta["kind"],
            "value": values[key],
            "step": meta.get("step"),
            "min": meta.get("min"),
            "max": meta.get("max"),
        })
    return rows


load_runtime_rules()
