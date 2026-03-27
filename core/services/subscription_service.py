import logging
import statistics
from collections import defaultdict

logger = logging.getLogger('core')

# ── Tuneable thresholds ────────────────────────────────────────────────────────

# Minimum number of transactions before a vendor is even considered.
MIN_OCCURRENCES = 2

# Fraction of consecutive date gaps that must land in a known interval bucket.
# 0.60 = at least 60% of gaps must be on-pattern. Prevents a single lucky gap
# from qualifying a vendor.
INTERVAL_CONSISTENCY_RATIO = 0.60

# Amounts are "on-pattern" if within this fraction of the median.
# 0.20 = ±20% tolerance (handles minor price changes like tax or rounding).
AMOUNT_TOLERANCE_PCT = 0.20

# Fraction of amounts that must be on-pattern.
AMOUNT_CONSISTENCY_RATIO = 0.60

# Known subscription interval buckets: (label, expected_days, ±tolerance_days).
# Ordered from shortest to longest; first match wins.
SUBSCRIPTION_INTERVALS = [
    ('weekly',      7,   3),
    ('biweekly',   14,   4),
    ('monthly',    30,   7),
    ('quarterly',  91,  14),
    ('semiannual', 182, 21),
    ('annual',     365, 30),
]


# ── Private helpers ────────────────────────────────────────────────────────────

def _match_interval(gaps: list[int]) -> str | None:
    """
    Return the label of the first interval bucket where ≥ INTERVAL_CONSISTENCY_RATIO
    of the supplied gaps fall within the bucket's tolerance, or None if no bucket
    matches.
    """
    if not gaps:
        return None
    n = len(gaps)
    for label, expected, tolerance in SUBSCRIPTION_INTERVALS:
        on_pattern = sum(1 for g in gaps if abs(g - expected) <= tolerance)
        if on_pattern / n >= INTERVAL_CONSISTENCY_RATIO:
            return label
    return None


def _amounts_consistent(amounts: list[float]) -> bool:
    """
    Return True if ≥ AMOUNT_CONSISTENCY_RATIO of amounts are within
    ±AMOUNT_TOLERANCE_PCT of the median amount.

    Single-transaction groups always return True (can't disprove consistency).
    Zero-median groups (free transactions) are excluded by the caller.
    """
    if len(amounts) < 2:
        return True
    median = statistics.median(amounts)
    if median == 0:
        return False  # free transactions are not subscriptions
    on_pattern = sum(
        1 for a in amounts if abs(a - median) / median <= AMOUNT_TOLERANCE_PCT
    )
    return on_pattern / len(amounts) >= AMOUNT_CONSISTENCY_RATIO


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_subscriptions(user) -> dict:
    """
    Detect recurring expense transactions for a user and flag them
    ``is_subscription=True``.

    A vendor is considered a subscription when it passes three gates:
      1. MIN_OCCURRENCES — at least N transactions exist.
      2. Interval consistency — ≥ 60 % of consecutive date gaps match a known
         subscription cadence (weekly / monthly / etc.).
      3. Amount consistency — ≥ 60 % of amounts are within ±20 % of the median.

    Only transactions from vendors that pass all gates are updated.
    Previously-flagged transactions are skipped (idempotent).

    Returns
    -------
    {
        "flagged_count":   int,
        "matched_vendors": [{"vendor", "interval", "occurrences", "avg_amount"}, ...],
        "skipped_vendors": [{"vendor", "reason", "occurrences"}, ...],
    }
    """
    from core.models import Transaction

    rows = (
        Transaction.objects
        .filter(user=user, transaction_type=Transaction.EXPENSE)
        .exclude(normalized_vendor='')
        .values('pk', 'normalized_vendor', 'date', 'amount', 'is_subscription')
        .order_by('normalized_vendor', 'date')
    )

    # Group by normalized_vendor (already ordered by date within each group)
    vendor_groups: dict[str, list] = defaultdict(list)
    for row in rows:
        vendor_groups[row['normalized_vendor']].append(row)

    new_subscription_pks: list[int] = []
    matched_vendors: list[dict] = []
    skipped_vendors: list[dict] = []

    for vendor, txns in vendor_groups.items():

        # Gate 1: minimum occurrences
        if len(txns) < MIN_OCCURRENCES:
            skipped_vendors.append({
                'vendor': vendor, 'reason': 'too_few_transactions',
                'occurrences': len(txns),
            })
            continue

        amounts = [float(t['amount']) for t in txns]
        gaps = [
            (txns[i + 1]['date'] - txns[i]['date']).days
            for i in range(len(txns) - 1)
        ]

        # Gate 2: interval consistency
        interval = _match_interval(gaps)
        if interval is None:
            skipped_vendors.append({
                'vendor': vendor, 'reason': 'irregular_intervals',
                'occurrences': len(txns),
            })
            continue

        # Gate 3: amount consistency
        if not _amounts_consistent(amounts):
            skipped_vendors.append({
                'vendor': vendor, 'reason': 'inconsistent_amounts',
                'occurrences': len(txns),
            })
            continue

        # All gates passed — collect transactions not yet flagged
        newly_flagged = [t['pk'] for t in txns if not t['is_subscription']]
        new_subscription_pks.extend(newly_flagged)
        matched_vendors.append({
            'vendor': vendor,
            'interval': interval,
            'occurrences': len(txns),
            'avg_amount': round(sum(amounts) / len(amounts), 2),
        })

    if new_subscription_pks:
        Transaction.objects.filter(pk__in=new_subscription_pks).update(is_subscription=True)

    logger.info(
        'detect_subscriptions: user=%s flagged=%d matched_vendors=%d skipped_vendors=%d',
        user.id, len(new_subscription_pks), len(matched_vendors), len(skipped_vendors),
    )

    return {
        'flagged_count': len(new_subscription_pks),
        'matched_vendors': matched_vendors,
        'skipped_vendors': skipped_vendors,
    }
