

import csv

from normalize import load_payments, load_settlements, load_ledger
from deterministic_match import run_deterministic_matching
from fuzzy_candidates import generate_fuzzy_candidates


def load_ground_truth(path: str) -> dict:
    """Returns {payment_id: {settlement_id, invoice_id, label, case_type}}"""
    gt = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["payment_id"] == "NONE":
                continue  # orphan settlements have no payment to evaluate against
            gt[row["payment_id"]] = row
    return gt


def load_ai_results(path: str) -> dict:
    """Returns {payment_id: {verdict, matched_settlement_id, confidence, ...}}"""
    results = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                results[row["payment_id"]] = row
    except FileNotFoundError:
        print(f"WARNING: {path} not found — run ai_resolver.py first. "
              f"Evaluating deterministic-only results.")
    return results


def build_final_verdicts(det_results, ai_results: dict) -> dict:
    """
    Combine deterministic + AI results into one final verdict per payment.
    Returns {payment_id: {final_status, final_settlement_id, source}}
    """
    final = {}

    for r in det_results:
        if r.status == "MATCHED":
            final[r.payment_id] = {
                "final_status": "MATCHED",
                "final_settlement_id": r.settlement_id,
                "source": "deterministic",
            }
        else:
            # was a CANDIDATE — check if the AI resolver handled it
            ai = ai_results.get(r.payment_id)
            if ai and ai["verdict"] == "match":
                final[r.payment_id] = {
                    "final_status": "MATCHED",
                    "final_settlement_id": ai["matched_settlement_id"],
                    "source": "ai_resolver",
                }
            else:
                # ai said no_match, needs_human_review, or wasn't run at all
                final[r.payment_id] = {
                    "final_status": "EXCEPTION",
                    "final_settlement_id": None,
                    "source": "ai_resolver" if ai else "unresolved_no_ai_data",
                }

    return final


def evaluate(final_verdicts: dict, ground_truth: dict):
    total = len(ground_truth)
    tp = 0   # true positive: we said MATCH, ground truth says MATCH, settlement_id correct
    fp = 0   # false positive: we said MATCH, but it's wrong (wrong settlement OR gt says EXCEPTION)
    fn = 0   # false negative: ground truth says MATCH, we said EXCEPTION (missed it)
    tn = 0   # true negative: ground truth says EXCEPTION, we correctly said EXCEPTION

    exception_breakdown = {}   # case_type -> count of correctly-flagged exceptions
    missed_exceptions = []     # ground truth EXCEPTION cases we wrongly auto-matched
    wrong_matches = []         # we matched, but to the WRONG settlement
    missed_matches = []        # ground truth MATCH cases we failed to resolve

    for payment_id, gt in ground_truth.items():
        pred = final_verdicts.get(payment_id)
        if pred is None:
            continue  # shouldn't happen, but guard against it

        gt_is_match = gt["label"] == "MATCH"
        pred_is_match = pred["final_status"] == "MATCHED"

        if gt_is_match and pred_is_match:
            if pred["final_settlement_id"] == gt["settlement_id"]:
                tp += 1
            else:
                fp += 1
                wrong_matches.append((payment_id, pred["final_settlement_id"], gt["settlement_id"]))

        elif gt_is_match and not pred_is_match:
            fn += 1
            missed_matches.append((payment_id, gt["case_type"]))

        elif not gt_is_match and pred_is_match:
            fp += 1
            missed_exceptions.append((payment_id, gt["case_type"]))

        elif not gt_is_match and not pred_is_match:
            tn += 1
            exception_breakdown[gt["case_type"]] = exception_breakdown.get(gt["case_type"], 0) + 1

    auto_matched = tp + fp   # everything we claimed as a match
    precision = tp / auto_matched if auto_matched > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    match_rate = (tp + fp) / total  # % of records we resolved with a match at all
    exception_rate = 1 - match_rate

    print("=" * 60)
    print("LEDGERLENS — RECONCILIATION BENCHMARK")
    print("=" * 60)
    print(f"Records evaluated:        {total}")
    print(f"Auto-matched:             {auto_matched}  ({match_rate:.1%})")
    print(f"Exceptions (unresolved):  {total - auto_matched}  ({exception_rate:.1%})")
    print()
    print(f"Precision (of auto-matched, % actually correct):  {precision:.1%}")
    print(f"Recall (of true matches, % we successfully found): {recall:.1%}")
    print()
    print(f"True positives  (correct matches):        {tp}")
    print(f"False positives (wrong/bad matches):       {fp}")
    print(f"False negatives (missed real matches):     {fn}")
    print(f"True negatives  (correctly flagged excpt): {tn}")
    print()

    if exception_breakdown:
        print("-" * 60)
        print("Correctly identified exceptions, by type:")
        for case_type, count in sorted(exception_breakdown.items()):
            print(f"  {case_type:35} {count}")

    if wrong_matches:
        print("-" * 60)
        print(f"⚠ WRONG MATCHES ({len(wrong_matches)}) — matched, but to the wrong settlement:")
        for payment_id, our_stl, correct_stl in wrong_matches:
            print(f"  {payment_id}: we said {our_stl}, correct was {correct_stl}")

    if missed_matches:
        print("-" * 60)
        print(f"⚠ MISSED MATCHES ({len(missed_matches)}) — should have matched, we said exception:")
        for payment_id, case_type in missed_matches:
            print(f"  {payment_id} ({case_type})")

    if missed_exceptions:
        print("-" * 60)
        print(f"⚠ FALSE MATCHES ({len(missed_exceptions)}) — should have been an exception, we auto-matched it:")
        for payment_id, case_type in missed_exceptions:
            print(f"  {payment_id} ({case_type})")

    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="data")
    args = parser.parse_args()
    d = args.data_dir

    payments = load_payments(f"{d}/payments.csv")
    settlements = load_settlements(f"{d}/settlements.csv")
    ledger = load_ledger(f"{d}/ledger.csv")

    det_results = run_deterministic_matching(payments, settlements, ledger)
    ai_results = load_ai_results(f"{d}/ai_resolver_results.csv")
    ground_truth = load_ground_truth(f"{d}/ground_truth.csv")

    final_verdicts = build_final_verdicts(det_results, ai_results)
    evaluate(final_verdicts, ground_truth)