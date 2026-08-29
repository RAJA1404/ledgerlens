"""
LedgerLens — Step 3a: Fuzzy Candidate Generation

For payments the deterministic matcher couldn't resolve, we can't just give
up — we look for *plausible* settlement candidates using looser rules:
- amount within a wider tolerance (covers bigger fees/discounts)
- date within a wider window (covers delayed settlements)
- reference similarity (not exact match, but "close enough" to consider)

This does NOT decide matches. It just narrows down "who could this possibly
be" so the AI resolver (step 3b) only has to reason about a handful of real
candidates instead of comparing against every settlement in the dataset.
"""

import difflib

from normalize import load_payments, load_settlements, load_ledger, Payment, Settlement

WIDE_AMOUNT_TOLERANCE = 2500.00   # rupees — wide enough to surface real fee/discount cases
WIDE_DATE_TOLERANCE_DAYS = 3
MIN_REF_SIMILARITY = 0.4          # 0.0-1.0, how similar references need to be to even consider


def ref_similarity(a: str, b: str) -> float:
    """Simple string similarity between two normalized references."""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def generate_fuzzy_candidates(payment: Payment, settlements: list[Settlement],
                               already_claimed: set) -> list[dict]:
    """
    Returns a list of candidate dicts, each with the settlement and metadata
    about WHY it's a candidate (useful context for the AI resolver later).
    Sorted by how promising the candidate looks (best first).
    """
    candidates = []
    for s in settlements:
        if s.settlement_id in already_claimed:
            continue

        amount_diff = abs(s.amount - payment.amount)
        date_diff = abs((s.txn_date - payment.txn_date).days)
        similarity = ref_similarity(payment.ref_norm, s.ref_norm)

        amount_ok = amount_diff <= WIDE_AMOUNT_TOLERANCE
        date_ok = date_diff <= WIDE_DATE_TOLERANCE_DAYS
        ref_plausible = similarity >= MIN_REF_SIMILARITY

        # A candidate is worth considering if amount+date are plausible,
        # AND either the reference is somewhat similar OR the amount/date
        # match is very tight (covers cases with totally reformatted refs)
        tight_amount_date = amount_diff <= 100 and date_diff <= 1

        if amount_ok and date_ok and (ref_plausible or tight_amount_date):
            candidates.append({
                "settlement_id": s.settlement_id,
                "amount": s.amount,
                "date": s.txn_date.isoformat(),
                "reference_raw": s.ref_raw,
                "amount_diff": round(amount_diff, 2),
                "date_diff_days": date_diff,
                "ref_similarity": round(similarity, 2),
            })

    # best candidates first: lowest amount diff, then highest ref similarity
    candidates.sort(key=lambda c: (c["amount_diff"], -c["ref_similarity"]))
    return candidates


if __name__ == "__main__":
    from deterministic_match import run_deterministic_matching

    payments = load_payments("data/payments.csv")
    settlements = load_settlements("data/settlements.csv")
    ledger = load_ledger("data/ledger.csv")

    det_results = run_deterministic_matching(payments, settlements, ledger)
    matched_settlement_ids = {r.settlement_id for r in det_results if r.settlement_id}

    unresolved = [r for r in det_results if r.status == "CANDIDATE"]
    payments_by_id = {p.payment_id: p for p in payments}

    print(f"Generating fuzzy candidates for {len(unresolved)} unresolved payments\n")

    for r in unresolved[:5]:  # show first 5 as a preview
        payment = payments_by_id[r.payment_id]
        fuzzy = generate_fuzzy_candidates(payment, settlements, matched_settlement_ids)
        print(f"{r.payment_id} (₹{payment.amount}, {payment.txn_date}, ref={payment.ref_raw})")
        if fuzzy:
            for c in fuzzy[:2]:
                print(f"    -> candidate {c['settlement_id']}: ₹{c['amount']} "
                      f"(diff ₹{c['amount_diff']}), {c['date']}, "
                      f"ref_similarity={c['ref_similarity']}")
        else:
            print("    -> NO fuzzy candidates found (likely a genuine exception)")
        print()