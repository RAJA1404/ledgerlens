

from dataclasses import dataclass, field
from datetime import timedelta

from normalize import (
    load_payments, load_settlements, load_ledger,
    Payment, Settlement, LedgerEntry,
)

AMOUNT_FEE_TOLERANCE = 100.00   # rupees — covers normal gateway/bank fees
DATE_TOLERANCE_DAYS = 1


@dataclass
class MatchResult:
    payment_id: str
    settlement_id: str | None
    invoice_id: str | None
    status: str            # "MATCHED" | "CANDIDATE" | "EXCEPTION"
    reason_codes: list = field(default_factory=list)


def find_settlement_candidates(payment: Payment, settlements: list[Settlement]) -> list[Settlement]:
    """All settlements that plausibly correspond to this payment."""
    candidates = []
    for s in settlements:
        ref_match = s.ref_norm == payment.ref_norm and payment.ref_norm != ""
        amount_diff = abs(s.amount - payment.amount)
        amount_ok = amount_diff <= AMOUNT_FEE_TOLERANCE
        date_diff = abs((s.txn_date - payment.txn_date).days)
        date_ok = date_diff <= DATE_TOLERANCE_DAYS

        if ref_match and amount_ok and date_ok:
            candidates.append(s)
    return candidates


def find_ledger_match(payment: Payment, ledger: list[LedgerEntry]) -> LedgerEntry | None:
    """Ledger matching is stricter — amount and date should be exact,
    since the ledger is the company's own internal record (no bank fees
    or third-party formatting involved)."""
    exact = [
        l for l in ledger
        if l.vendor == payment.vendor
        and l.amount == payment.amount
        and l.txn_date == payment.txn_date
    ]
    return exact[0] if len(exact) == 1 else None


def run_deterministic_matching(payments, settlements, ledger) -> list[MatchResult]:
    results = []
    matched_settlement_ids = set()  # prevent double-using a settlement for two payments

    for payment in payments:
        candidates = find_settlement_candidates(payment, settlements)
        # exclude settlements already claimed by an earlier payment this run
        candidates = [c for c in candidates if c.settlement_id not in matched_settlement_ids]

        ledger_match = find_ledger_match(payment, ledger)

        if len(candidates) == 1:
            settlement = candidates[0]
            matched_settlement_ids.add(settlement.settlement_id)

            reasons = ["reference_exact_match"]
            if settlement.amount != payment.amount:
                reasons.append("amount_within_fee_tolerance")
            if settlement.txn_date != payment.txn_date:
                reasons.append("date_within_1_day")
            if ledger_match:
                reasons.append("ledger_confirmed")

            status = "MATCHED" if ledger_match else "CANDIDATE"
            if not ledger_match:
                reasons.append("no_ledger_entry_found")

            results.append(MatchResult(
                payment_id=payment.payment_id,
                settlement_id=settlement.settlement_id,
                invoice_id=ledger_match.invoice_id if ledger_match else None,
                status=status,
                reason_codes=reasons,
            ))

        elif len(candidates) == 0:
            results.append(MatchResult(
                payment_id=payment.payment_id,
                settlement_id=None,
                invoice_id=ledger_match.invoice_id if ledger_match else None,
                status="CANDIDATE",   # send to AI resolver — might still be
                                       # resolvable via fuzzy ref/amount logic
                reason_codes=["no_deterministic_settlement_candidate"],
            ))

        else:
            # multiple plausible settlements — genuinely ambiguous,
            # deterministic layer refuses to guess
            results.append(MatchResult(
                payment_id=payment.payment_id,
                settlement_id=None,
                invoice_id=ledger_match.invoice_id if ledger_match else None,
                status="CANDIDATE",
                reason_codes=[f"multiple_candidates_{len(candidates)}",
                              "requires_ai_or_human_resolution"],
            ))

    return results


def summarize(results: list[MatchResult]):
    total = len(results)
    matched = sum(1 for r in results if r.status == "MATCHED")
    candidate = sum(1 for r in results if r.status == "CANDIDATE")

    print(f"Deterministic pass complete")
    print(f"  Total payments:        {total}")
    print(f"  Fully matched:         {matched}  ({matched/total:.1%})")
    print(f"  Sent to AI resolver:   {candidate}  ({candidate/total:.1%})")
    print()

    # Show a few examples of each
    print("Example MATCHED:")
    for r in [r for r in results if r.status == "MATCHED"][:2]:
        print(f"  {r.payment_id} -> {r.settlement_id} -> {r.invoice_id} | {r.reason_codes}")
    print()
    print("Example CANDIDATE (needs AI resolver):")
    for r in [r for r in results if r.status == "CANDIDATE"][:3]:
        print(f"  {r.payment_id} -> settlement={r.settlement_id} | {r.reason_codes}")


if __name__ == "__main__":
    # NOTE: run this script from the ledgerlens/ root folder, e.g.:
    #   py src/deterministic_match.py
    payments = load_payments("data/payments.csv")
    settlements = load_settlements("data/settlements.csv")
    ledger = load_ledger("data/ledger.csv")

    results = run_deterministic_matching(payments, settlements, ledger)
    summarize(results)