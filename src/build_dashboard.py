

import argparse
import json
import re

from normalize import load_payments, load_settlements, load_ledger
from deterministic_match import run_deterministic_matching
from evaluate import load_ai_results, load_ground_truth, build_final_verdicts


def build_dashboard_data(data_dir: str) -> dict:
    payments = load_payments(f"{data_dir}/payments.csv")
    settlements = load_settlements(f"{data_dir}/settlements.csv")
    ledger = load_ledger(f"{data_dir}/ledger.csv")

    det_results = run_deterministic_matching(payments, settlements, ledger)
    ai_results = load_ai_results(f"{data_dir}/ai_resolver_results.csv")
    ground_truth = load_ground_truth(f"{data_dir}/ground_truth.csv")
    final_verdicts = build_final_verdicts(det_results, ai_results)

    payments_by_id = {p.payment_id: p for p in payments}
    settlements_by_id = {s.settlement_id: s for s in settlements}

    records = []
    tp = fp = fn = tn = 0

    for r in det_results:
        payment = payments_by_id[r.payment_id]
        gt = ground_truth.get(r.payment_id, {})
        final = final_verdicts[r.payment_id]
        ai = ai_results.get(r.payment_id, {})

        gt_is_match = gt.get("label") == "MATCH"
        pred_is_match = final["final_status"] == "MATCHED"

        correct = None
        if gt_is_match and pred_is_match:
            correct = (final["final_settlement_id"] == gt.get("settlement_id"))
            tp += 1 if correct else 0
            fp += 0 if correct else 1
        elif gt_is_match and not pred_is_match:
            correct = False
            fn += 1
        elif not gt_is_match and pred_is_match:
            correct = False
            fp += 1
        elif not gt_is_match and not pred_is_match:
            correct = True
            tn += 1

        matched_settlement = None
        if final["final_settlement_id"]:
            s = settlements_by_id.get(final["final_settlement_id"])
            if s:
                matched_settlement = {
                    "id": s.settlement_id, "amount": s.amount,
                    "date": s.txn_date.isoformat(), "reference": s.ref_raw,
                }

        default_reason = ("Resolved by exact rule match: reference, amount, "
                           "and date all align within tolerance.")
        records.append({
            "payment_id": payment.payment_id,
            "amount": payment.amount,
            "date": payment.txn_date.isoformat(),
            "reference": payment.ref_raw,
            "vendor": payment.vendor,
            "source": final["source"],
            "status": final["final_status"],
            "matched_settlement": matched_settlement,
            "confidence": float(ai.get("confidence", 1.0)) if ai
                          else (1.0 if final["source"] == "deterministic" else None),
            "reasoning": ai.get("reasoning", default_reason if final["source"] == "deterministic" else ""),
            "hard_rule_override": ai.get("hard_rule_override", "False") == "True" if ai else False,
            "ground_truth_label": gt.get("label"),
            "case_type": gt.get("case_type"),
            "correct": correct,
            "det_reason_codes": r.reason_codes,
        })

    total = len(records)
    matched = sum(1 for r in records if r["status"] == "MATCHED")

    summary = {
        "total": total,
        "matched": matched,
        "exceptions": total - matched,
        "match_rate": matched / total if total else 0,
        "precision": tp / (tp + fp) if (tp + fp) > 0 else 0,
        "recall": tp / (tp + fn) if (tp + fn) > 0 else 0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "deterministic_count": sum(1 for r in records if r["source"] == "deterministic"),
        "ai_count": sum(1 for r in records if r["source"] == "ai_resolver"),
    }

    return {"summary": summary, "records": records}


def inject_into_dashboard(data: dict, template_path: str, output_path: str):
    with open(template_path, encoding="utf-8") as f:
        html = f.read()

    json_str = json.dumps(data)
    # Replace whatever data blob is currently embedded (between "const DATA ="
    # and the following semicolon-newline) so this is safe to re-run repeatedly.
    new_html = re.sub(
        r"const DATA = .*?;\n",
        lambda m: f"const DATA = {json_str};\n",
        html,
        count=1,
        flags=re.DOTALL,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--dashboard-path", type=str, default="dashboard/index.html")
    args = parser.parse_args()

    data = build_dashboard_data(args.data_dir)
    inject_into_dashboard(data, args.dashboard_path, args.dashboard_path)

    s = data["summary"]
    print(f"Dashboard updated: {args.dashboard_path}")
    print(f"  {s['matched']}/{s['total']} matched ({s['match_rate']:.1%}), "
          f"precision {s['precision']:.1%}, recall {s['recall']:.1%}")