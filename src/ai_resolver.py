

import json
import os
import time

from openai import OpenAI, APIError, RateLimitError, APIStatusError

from normalize import Payment
from fuzzy_candidates import generate_fuzzy_candidates

# Hard safety rule — the AI cannot override this, no matter its confidence
HARD_MAX_AMOUNT_DIFF = 500.00

MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 5   # doubles each retry: 5s, 10s, 20s, 40s

client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)
MODEL_NAME = "openai/gpt-oss-20b"   # Groq's current recommended model (llama-3.3-70b-versatile was deprecated June 2026)

SYSTEM_PROMPT = """You are a financial reconciliation investigator. You are \
given ONE payment record and a short list of candidate settlement records \
that MIGHT correspond to it. Your job is to reason carefully and report your \
confidence honestly.

Rules:
- If evidence strongly supports one candidate being the true match, say so \
with high confidence.
- If evidence is ambiguous, or no candidate is convincing, say \
"needs_human_review" — do NOT force a verdict to seem decisive.
- Base your reasoning only on the data provided. Do not assume facts not in \
evidence.
- Always explain what is missing or inconsistent if you cannot confidently \
resolve it.

Return ONLY valid JSON in exactly this structure, nothing else:
{
  "verdict": "match" | "needs_human_review" | "no_match",
  "matched_settlement_id": "string or null",
  "confidence": 0.0-1.0,
  "reasoning": "1-2 sentence explanation",
  "evidence": ["specific point 1", "specific point 2"]
}
"""


def resolve_with_ai(payment: Payment, candidates: list[dict]) -> dict:
    """Send one payment + its candidates to the LLM and return its structured verdict."""
    if not candidates:
        return {
            "verdict": "no_match",
            "matched_settlement_id": None,
            "confidence": 1.0,
            "reasoning": "No plausible settlement candidates found within tolerance.",
            "evidence": ["zero_fuzzy_candidates"],
        }

    user_prompt = f"""Payment record:
{json.dumps({
    "payment_id": payment.payment_id,
    "amount": payment.amount,
    "date": payment.txn_date.isoformat(),
    "reference": payment.ref_raw,
    "vendor": payment.vendor,
}, indent=2)}

Candidate settlements:
{json.dumps(candidates, indent=2)}

Investigate and return your verdict as JSON."""

    response_text, last_error = _call_llm_with_retry(SYSTEM_PROMPT, user_prompt)

    if response_text is None:
        # All retries exhausted — don't crash the whole batch, route this
        # one record to human review and keep going
        return {
            "verdict": "needs_human_review",
            "matched_settlement_id": None,
            "confidence": 0.0,
            "reasoning": f"AI service unavailable after {MAX_RETRIES} retries "
                         f"({last_error}); routed to manual review.",
            "evidence": ["ai_service_unavailable"],
        }

    try:
        result = json.loads(response_text)
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        result = {
            "verdict": "needs_human_review",
            "matched_settlement_id": None,
            "confidence": 0.0,
            "reasoning": "AI response could not be parsed — routed to manual review.",
            "evidence": ["ai_response_parse_error"],
        }

    return result


def apply_hard_validation(payment: Payment, ai_result: dict, candidates: list[dict]) -> dict:
    """
    The safety layer: even if the AI says MATCH with high confidence, if the
    amount difference exceeds HARD_MAX_AMOUNT_DIFF, we override to EXCEPTION.
    This rule cannot be bypassed by the AI's reasoning — it's a hard financial
    control, not a suggestion.
    """
    if ai_result["verdict"] != "match" or not ai_result.get("matched_settlement_id"):
        return ai_result

    matched = next((c for c in candidates
                     if c["settlement_id"] == ai_result["matched_settlement_id"]), None)
    if matched and matched["amount_diff"] > HARD_MAX_AMOUNT_DIFF:
        ai_result = dict(ai_result)  # don't mutate original
        ai_result["verdict"] = "needs_human_review"
        ai_result["reasoning"] += (
            f" [OVERRIDDEN BY HARD RULE: amount difference of ₹{matched['amount_diff']} "
            f"exceeds the ₹{HARD_MAX_AMOUNT_DIFF} safety threshold — AI match "
            f"suggestion rejected regardless of stated confidence.]"
        )
        ai_result["hard_rule_override"] = True
    else:
        ai_result["hard_rule_override"] = False

    return ai_result


if __name__ == "__main__":
    import argparse
    import csv
    from normalize import load_payments, load_settlements, load_ledger
    from deterministic_match import run_deterministic_matching

    payments = load_payments("data/payments.csv")
    settlements = load_settlements("data/settlements.csv")
    ledger = load_ledger("data/ledger.csv")

    det_results = run_deterministic_matching(payments, settlements, ledger)
    matched_settlement_ids = {r.settlement_id for r in det_results if r.settlement_id}
    unresolved = [r for r in det_results if r.status == "CANDIDATE"]
    payments_by_id = {p.payment_id: p for p in payments}

    print(f"Running AI resolver on all {len(unresolved)} unresolved payments...\n")

    # Resume support: if a previous run already produced results, load them
    # so a crash/interrupt doesn't force you to re-pay/re-call for records
    # that already succeeded.
    output_path = f"{d}/ai_resolver_results.csv"
    already_done = {}
    if os.path.exists(output_path):
        with open(output_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                already_done[row["payment_id"]] = row
        print(f"Found {len(already_done)} previously completed results — resuming.\n")

    ai_output_rows = list(already_done.values())
    remaining = [r for r in unresolved if r.payment_id not in already_done]

    print(f"Processing {len(remaining)} payments in batches of {BATCH_SIZE} "
          f"({-(-len(remaining) // BATCH_SIZE) if remaining else 0} API calls "
          f"instead of {len(remaining)} — this is the optimization: fewer, "
          f"larger calls instead of one call per record)\n")

    # Chunk remaining payments into batches
    batches = [remaining[i:i + BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        print(f"--- Batch {batch_num}/{len(batches)} ({len(batch)} payments) ---")

        payments_with_candidates = []
        for r in batch:
            payment = payments_by_id[r.payment_id]
            candidates = generate_fuzzy_candidates(payment, settlements, matched_settlement_ids)
            payments_with_candidates.append((payment, candidates))

        batch_results = resolve_batch_with_ai(payments_with_candidates)

        for payment, candidates in payments_with_candidates:
            ai_result = batch_results.get(payment.payment_id, {
                "verdict": "needs_human_review",
                "matched_settlement_id": None,
                "confidence": 0.0,
                "reasoning": "Payment missing from batch response — routed to manual review.",
                "evidence": ["missing_from_batch_response"],
            })
            final = apply_hard_validation(payment, ai_result, candidates)

            print(f"{payment.payment_id} (₹{payment.amount}, ref={payment.ref_raw})")
            print(f"  Verdict: {final['verdict']} (confidence {final['confidence']})")
            print(f"  Matched settlement: {final.get('matched_settlement_id')}")
            print(f"  Reasoning: {final['reasoning']}")
            if final.get("hard_rule_override"):
                print(f"  ⚠ HARD RULE OVERRIDE APPLIED")

            ai_output_rows.append({
                "payment_id": payment.payment_id,
                "verdict": final["verdict"],
                "matched_settlement_id": final.get("matched_settlement_id") or "",
                "confidence": final["confidence"],
                "reasoning": final["reasoning"],
                "hard_rule_override": final.get("hard_rule_override", False),
            })
        print()

        # Save after EVERY batch, not just at the end — so if the script
        # crashes or you close the terminal partway through, you keep all
        # progress made so far and can just re-run to pick up where it left off.
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "payment_id", "verdict", "matched_settlement_id",
                "confidence", "reasoning", "hard_rule_override",
            ])
            writer.writeheader()
            writer.writerows(ai_output_rows)

        time.sleep(2)  # small pause between calls to stay under per-minute rate limits

    matches = sum(1 for row in ai_output_rows if row["verdict"] == "match")
    review = sum(1 for row in ai_output_rows if row["verdict"] == "needs_human_review")
    no_match = sum(1 for row in ai_output_rows if row["verdict"] == "no_match")

    print("=" * 50)
    print(f"AI resolver summary:")
    print(f"  Resolved as match:        {matches}")
    print(f"  Needs human review:       {review}")
    print(f"  No match found:           {no_match}")
    print(f"\nResults saved to {output_path}")