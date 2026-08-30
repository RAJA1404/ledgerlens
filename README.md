# LedgerLens — AI Reconciliation Controller

Built for the Razorpay AI Buildathon — Track 04: AI Finance Controller

> Closes one finance-ops loop: reconciling payments, bank settlements, and
> internal ledger records — automatically, safely, and honestly.

---

## Results (reproducible — see "Run it yourself" below)

Benchmarked against a known ground truth on 117 synthetic payment records:

| Metric | Result |
|---|---|
| Records processed | 117 |
| Auto-matched | 108 (92.3%) |
| Exceptions (unresolved, sent for human review) | 9 (7.7%) |
| **Precision** (of auto-matched, % actually correct) | **99.1%** |
| **Recall** (of real matches, % successfully found) | **100.0%** |

**We do not claim 100% accuracy.** One record (`pay_1102`) was matched to the
wrong settlement — see [Known Limitations](#known-limitations) for exactly
why, and how we'd fix it. A system that claims perfect accuracy on messy
financial data is a red flag, not an achievement.

---

## The problem

When a customer pays, that single transaction creates three separate records
across three systems that don't naturally agree with each other:

1. **Payment gateway** — records the payment
2. **Bank settlement** — confirms money actually landed (often a day later,
   often with a fee deducted, often reformatted)
3. **Internal ledger** — the company's own accounting record

A human "finance controller" manually cross-checks these — slow, tedious,
and error-prone. LedgerLens automates the ~85-90% of cases that are safely
automatable, and honestly flags the rest instead of guessing.

---

## Architecture

![Pipeline overview](architecture/pipeline_overview.svg)
![AI resolution path](architecture/ai_resolution_path.svg)

Text version, for anyone viewing this outside GitHub's SVG renderer:

```
                ┌─────────────────┐
                │  3 CSV sources   │
                │  payments /      │
                │  settlements /   │
                │  ledger          │
                └────────┬─────────┘
                         ↓
                ┌─────────────────┐
                │  Normalization   │   <- clean refs, amounts, dates
                └────────┬─────────┘
                         ↓
                ┌─────────────────┐
                │  Deterministic   │   <- exact ref + amount(±₹100) + date(±1 day)
                │  Matcher         │      NO AI. Handles ~84% of records.
                └────────┬─────────┘
                         ↓
              ┌──────────┴──────────┐
              ↓                     ↓
         MATCHED                CANDIDATE (unresolved)
                                     ↓
                          ┌─────────────────┐
                          │  Fuzzy Candidate │   <- wider tolerance + reference
                          │  Generator       │      similarity scoring
                          └────────┬─────────┘
                                   ↓
                          ┌─────────────────┐
                          │  AI Resolver     │   <- LLM reasons over evidence,
                          │  (Gemini)        │      returns structured verdict +
                          └────────┬─────────┘      confidence + reasoning
                                   ↓
                          ┌─────────────────┐
                          │  Hard Validation │   <- AI CANNOT override this.
                          │  (amount ≤ ₹500) │      Rejects risky AI matches
                          └────────┬─────────┘      regardless of confidence.
                                   ↓
                    ┌──────────────┴──────────────┐
                    ↓                              ↓
              FINAL MATCH                    EXCEPTION QUEUE
                    ↓                              ↓
                    └──────────────┬───────────────┘
                                   ↓
                          ┌─────────────────┐
                          │  Evaluation vs   │   <- scored against known
                          │  Ground Truth    │      ground truth, not vibes
                          └─────────────────┘
```

### Why deterministic-first, not "ask the AI"

Financial facts (does this amount match, is this the same reference) should
never be decided probabilistically. The deterministic layer handles anything
a computer can calculate with certainty — no LLM call, no cost, no risk of
hallucination. The AI is only invoked for the genuinely ambiguous ~16% of
cases: reformatted references, near-miss amounts, missing records.

### Why a hard validation layer sits after the AI, not just a prompt instruction

An LLM can be told "don't match if the amount differs by more than ₹500" —
but a prompt instruction is a suggestion, not a guarantee. The hard
validation layer is plain Python that re-checks every AI-proposed match
against that rule and **overrides** the AI's verdict if it's violated,
regardless of how confident the AI claims to be. This actually fired during
testing — see `pay_1103` in the resolver output, where the AI proposed a
match at high confidence and the hard rule correctly rejected it.

---

## Run it yourself

Requires Python 3.10+ and a free [Gemini API key](https://aistudio.google.com)
(no credit card needed).

```bash
git clone https://github.com/RAJA1404/ledgerlens.git
cd ledgerlens
pip install -r requirements.txt

# set your API key (Windows)
setx GEMINI_API_KEY "your-key-here"
# (Mac/Linux: export GEMINI_API_KEY="your-key-here")

# run the full pipeline and see the benchmark
py run_all.py
```

To reproduce the benchmark **without any API calls or cost** (deterministic
layer only):

```bash
py run_all.py --skip-ai
```

To regenerate the synthetic dataset from scratch (same seed, same output —
fully reproducible):

```bash
py run_all.py --regenerate
```

---

## Repository structure

```
ledgerlens/
├── data/
│   ├── payments.csv           # 117 synthetic payment records
│   ├── settlements.csv        # 125 synthetic bank settlement records
│   ├── ledger.csv             # 114 synthetic internal ledger records
│   ├── ground_truth.csv       # known-correct answer key, used for scoring
│   ├── vendor_aliases.csv     # realistic vendor name variants
│   └── ai_resolver_results.csv # cached AI resolver output (avoids re-calling API)
├── src/
│   ├── generate_data.py       # synthetic data generator (seeded, reproducible)
│   ├── normalize.py           # data cleaning / normalization
│   ├── deterministic_match.py # rule-based matcher (no AI)
│   ├── fuzzy_candidates.py    # candidate narrowing for ambiguous cases
│   ├── ai_resolver.py         # LLM reasoning + hard validation
│   └── evaluate.py            # scores results against ground truth
├── run_all.py                 # single entry point, runs the full pipeline
├── requirements.txt
└── README.md
```

---

## Known limitations

Being transparent about this is deliberate — see the note at the top of
this README about why 100% accuracy would be a red flag, not a strength.

**`pay_1102` — one false match.** The AI resolver matched this payment to
settlement `stl_5124`, but ground truth shows this payment's true settlement
was actually missing (a genuine `missing_settlement` exception). The fuzzy
candidate generator surfaced `stl_5124` as a plausible decoy because it was
amount/date-adjacent, and the AI resolver's confidence in the vendor-name
signal wasn't checked against ledger vendor data before finalizing.

**Fix in a production system:** the fuzzy candidate generator should be
vendor-aware — cross-checking candidates against the ledger's recorded
vendor for that payment, not just amount and date proximity. This would
eliminate this specific class of error. We chose not to over-fit this fix
into the current version to keep the evaluation honest and unmodified after
seeing this result.

**Other scope limitations (by design, for a buildathon timeframe):**
- No OCR/PDF parsing — structured CSV/JSON input only
- No multi-currency or tax handling
- No real bank/payment gateway API integration (synthetic data only,
  architected so real sources could be swapped in)
- Vendor alias table is static, not learned/updated over time

---

## Judging criteria — how this project addresses them

| Criterion | How this project addresses it |
|---|---|
| Real-world usefulness | Reconciliation is a universal, recurring finance-ops bottleneck |
| Non-trivial AI integration | AI only touches the ~16% of genuinely ambiguous cases; deterministic rules handle the rest — not a thin GPT wrapper |
| Code quality | Modular pipeline, each stage independently testable and readable |
| System architecture | Deterministic-first, AI-assisted, hard-validated — a real layered design, not a single LLM call |
| Product thinking | Honest exception queue over false confidence; documented limitations |
| Defensible engineering decisions | Every architectural choice above has a concrete reason, provable in the actual output (see `pay_1103` override) |
