"""
Behavioural analysis (handoff Phase 4): compare current activity against
the customer's OWN history, not just fixed universal thresholds. Provides
generic, reusable deviation-detection helpers (median/percentage deviation,
robust-to-outliers) that app/pipeline/anomalies.py and the reports apply
per category. A single deviation is a signal for explanation/review, never
a fraud conclusion (handoff instruction, enforced by callers never using
words like "fraud").
"""
from decimal import Decimal
from statistics import median, mean, pstdev
from app.config import thresholds as cfg


def median_deviation(current: Decimal, history: list) -> dict:
    """
    Robust percentage deviation of `current` from the median of `history`
    (median chosen over mean because it isn't distorted by a single
    outlier month, per handoff: "use robust methods where outliers distort
    averages"). Returns None values when there isn't enough history to
    judge deviation, with a provisional flag rather than a forced number.
    """
    history = [h for h in history if h is not None]
    if len(history) < cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION:
        return {
            "deviation_pct": None, "baseline_median": float(median(history)) if history else None,
            "provisional": True, "history_points": len(history),
            "note": f"Fewer than {cfg.MIN_HISTORY_MONTHS_FOR_DEVIATION} historical points; deviation is provisional.",
        }

    baseline = Decimal(str(median(history)))
    if baseline == 0:
        deviation_pct = None if current == 0 else float("inf")
    else:
        deviation_pct = float((current - baseline) / baseline * 100)

    severity = "normal"
    if deviation_pct is not None:
        abs_dev = abs(deviation_pct)
        if abs_dev >= float(cfg.DEVIATION_HIGH_PCT):
            severity = "high"
        elif abs_dev >= float(cfg.DEVIATION_WARN_PCT):
            severity = "warn"

    return {
        "deviation_pct": deviation_pct,
        "baseline_median": float(baseline),
        "current": float(current),
        "provisional": False,
        "history_points": len(history),
        "severity": severity,
    }


def coefficient_of_variation(values: list) -> float | None:
    """Volatility measure: stdev / mean. None when fewer than 2 points or mean is 0."""
    values = [float(v) for v in values if v is not None]
    if len(values) < 2 or mean(values) == 0:
        return None
    return pstdev(values) / mean(values)


def frequency_deviation(current_count: int, history_counts: list) -> dict:
    """Same shape as median_deviation but for event counts (e.g. transfers/month, withdrawals/month)."""
    return median_deviation(Decimal(current_count), [Decimal(c) for c in history_counts])


def compare_monthly_series(by_month: dict, recent_months: int = 3) -> dict:
    """
    Split a {month: value} series into a "recent" window and a "prior"
    baseline of the same length, for trend comparisons (handoff: "Income
    consistency... monthly trends", "Last 3 months vs prior" style checks).
    Returns None baselines when there isn't enough history.
    """
    months = sorted(by_month.keys())
    if len(months) < recent_months * 2:
        return {
            "recent_total": sum(by_month[m] for m in months[-recent_months:]) if months else None,
            "prior_total": None, "change_pct": None,
            "provisional": True,
            "note": f"Need at least {recent_months * 2} months of history for a recent-vs-prior comparison.",
        }

    recent = months[-recent_months:]
    prior = months[-2 * recent_months:-recent_months]
    recent_total = sum(by_month[m] for m in recent)
    prior_total = sum(by_month[m] for m in prior)

    change_pct = None
    if prior_total:
        change_pct = (recent_total - prior_total) / prior_total * 100

    return {
        "recent_months": recent, "recent_total": recent_total,
        "prior_months": prior, "prior_total": prior_total,
        "change_pct": change_pct, "provisional": False,
    }
