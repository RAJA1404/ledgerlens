

import csv
import os
import random
from datetime import date, timedelta

random.seed(42)

OUTPUT_DIR = "/home/claude/ledgerlens/data"

FIRST_NAMES = ["Ravi", "Priya", "Arjun", "Sneha", "Vikram", "Anita", "Karan",
               "Divya", "Rohan", "Meera", "Aditya", "Kavya", "Suresh", "Pooja",
               "Nikhil", "Ishita", "Manoj", "Riya", "Aman", "Neha"]
LAST_NAMES = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Kapoor",
              "Menon", "Joshi", "Chatterjee", "Bose", "Rao", "Malhotra", "Singh"]

VENDOR_CANONICAL = ["Amazon Seller Services", "Flipkart Internet", "Swiggy",
                    "Zomato", "Myntra Designs", "BigBasket", "Nykaa E-Retail",
                    "Ola Cabs", "Uber India", "PharmEasy"]

# Realistic alias variants for the same vendor — used in ledger/settlement rows
VENDOR_ALIASES = {
    "Amazon Seller Services": ["AMZN Mktp IN*AB{}", "AMAZON INDIA", "AMZN*{}"],
    "Flipkart Internet": ["FLIPKART*{}", "FKRT INTERNET PVT LTD", "Flipkart-{}"],
    "Swiggy": ["SWIGGY*ORDER{}", "BUNDL TECH SWIGGY", "Swiggy Ord {}"],
    "Zomato": ["ZOMATO ONLINE", "ZOMATO*{}", "Zomato Ltd"],
    "Myntra Designs": ["MYNTRA*{}", "MYNTRA DESIGNS PVT", "Myntra-{}"],
    "BigBasket": ["BIGBASKET*{}", "SUPERMARKET GROCERY BB", "BigBasket Ord{}"],
    "Nykaa E-Retail": ["NYKAA*{}", "FSN E-COMMERCE NYKAA", "Nykaa-{}"],
    "Ola Cabs": ["OLA*TRIP{}", "ANI TECHNOLOGIES OLA", "Ola Cabs {}"],
    "Uber India": ["UBER *TRIP{}", "UBER INDIA SYSTEMS", "Uber-{}"],
    "PharmEasy": ["PHARMEASY*{}", "API HOLDINGS PHARMEASY", "PharmEasy Ord{}"],
}

START_DATE = date(2026, 8, 1)


def random_date_offset(base_d, max_days=25):
    return base_d + timedelta(days=random.randint(0, max_days))


def make_ref(i):
    return f"ORD-{8000 + i}"


def money(amount):
    return round(amount, 2)


def generate(scale: float = 1.0, output_dir: str = None):
    """
    scale: multiplier applied to the base record counts (1.0 = original 120,
           3.0 = ~360 records) while keeping the same case-type proportions.
    output_dir: where to write the CSVs. Defaults to OUTPUT_DIR (data/).
    """
    out_dir = output_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    n_clean = round(78 * scale)       # exact, clean matches across all 3 sources
    n_noisy = round(20 * scale)       # resolvable but with realistic corruption
    n_exception = round(13 * scale)   # genuine exceptions (missing / real mismatch)
    n_duplicate = round(9 * scale)    # duplicate or ambiguous candidate cases
    total = n_clean + n_noisy + n_exception + n_duplicate

    payments = []
    settlements = []
    ledger = []
    ground_truth = []

    pay_id_counter = 1000
    stl_id_counter = 5000
    inv_id_counter = 8000

    record_idx = 0

    # ---------- 1. CLEAN MATCHES ----------
    for _ in range(n_clean):
        record_idx += 1
        vendor = random.choice(VENDOR_CANONICAL)
        customer = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        amount = money(random.uniform(199, 15000))
        d = random_date_offset(START_DATE)
        ref = make_ref(record_idx)

        pay_id = f"pay_{pay_id_counter}"; pay_id_counter += 1
        stl_id = f"stl_{stl_id_counter}"; stl_id_counter += 1
        inv_id = f"INV-{inv_id_counter}"; inv_id_counter += 1

        payments.append([pay_id, amount, d.isoformat(), ref, vendor])
        settlements.append([stl_id, amount, d.isoformat(), ref])
        ledger.append([inv_id, amount, d.isoformat(), customer, vendor])

        ground_truth.append([pay_id, stl_id, inv_id, "MATCH", "clean_exact"])

    # ---------- 2. NOISY BUT RESOLVABLE ----------
    noise_types = ["date_shift", "ref_reformat", "fee_deducted", "typo_ref"]
    for i in range(n_noisy):
        record_idx += 1
        noise = noise_types[i % len(noise_types)]
        vendor = random.choice(VENDOR_CANONICAL)
        customer = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        amount = money(random.uniform(199, 15000))
        d = random_date_offset(START_DATE)
        ref = make_ref(record_idx)

        pay_id = f"pay_{pay_id_counter}"; pay_id_counter += 1
        stl_id = f"stl_{stl_id_counter}"; stl_id_counter += 1
        inv_id = f"INV-{inv_id_counter}"; inv_id_counter += 1

        settle_amount = amount
        settle_date = d
        settle_ref = ref

        if noise == "date_shift":
            settle_date = d + timedelta(days=1)
        elif noise == "ref_reformat":
            alias_pattern = random.choice(VENDOR_ALIASES[vendor])
            settle_ref = alias_pattern.format(record_idx)
        elif noise == "fee_deducted":
            settle_amount = money(amount - random.choice([10, 20, 50, 99]))
        elif noise == "typo_ref":
            settle_ref = ref.replace("ORD", "0RD") if random.random() < 0.5 else ref[:-1] + "X"

        payments.append([pay_id, amount, d.isoformat(), ref, vendor])
        settlements.append([stl_id, settle_amount, settle_date.isoformat(), settle_ref])
        ledger.append([inv_id, amount, d.isoformat(), customer, vendor])

        ground_truth.append([pay_id, stl_id, inv_id, "MATCH", f"noisy_{noise}"])

    # ---------- 3. GENUINE EXCEPTIONS ----------
    exception_types = ["missing_settlement", "amount_mismatch_large",
                        "missing_ledger", "orphan_settlement"]
    for i in range(n_exception):
        record_idx += 1
        exc = exception_types[i % len(exception_types)]
        vendor = random.choice(VENDOR_CANONICAL)
        customer = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        amount = money(random.uniform(199, 15000))
        d = random_date_offset(START_DATE)
        ref = make_ref(record_idx)

        pay_id = f"pay_{pay_id_counter}"; pay_id_counter += 1
        stl_id = f"stl_{stl_id_counter}"; stl_id_counter += 1
        inv_id = f"INV-{inv_id_counter}"; inv_id_counter += 1

        if exc == "missing_settlement":
            payments.append([pay_id, amount, d.isoformat(), ref, vendor])
            ledger.append([inv_id, amount, d.isoformat(), customer, vendor])
            ground_truth.append([pay_id, "NONE", inv_id, "EXCEPTION", "missing_settlement"])

        elif exc == "amount_mismatch_large":
            settle_amount = money(amount - random.uniform(500, 2000))
            payments.append([pay_id, amount, d.isoformat(), ref, vendor])
            settlements.append([stl_id, settle_amount, d.isoformat(), ref])
            ledger.append([inv_id, amount, d.isoformat(), customer, vendor])
            ground_truth.append([pay_id, stl_id, inv_id, "EXCEPTION", "amount_mismatch_large"])

        elif exc == "missing_ledger":
            payments.append([pay_id, amount, d.isoformat(), ref, vendor])
            settlements.append([stl_id, amount, d.isoformat(), ref])
            ground_truth.append([pay_id, stl_id, "NONE", "EXCEPTION", "missing_ledger"])

        elif exc == "orphan_settlement":
            # settlement with no corresponding payment/ledger at all
            settlements.append([stl_id, amount, d.isoformat(), ref])
            ground_truth.append(["NONE", stl_id, "NONE", "EXCEPTION", "orphan_settlement"])

    # ---------- 4. DUPLICATES / AMBIGUOUS ----------
    for i in range(n_duplicate):
        record_idx += 1
        vendor = random.choice(VENDOR_CANONICAL)
        customer = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        amount = money(random.uniform(199, 15000))
        d = random_date_offset(START_DATE)
        ref = make_ref(record_idx)

        pay_id = f"pay_{pay_id_counter}"; pay_id_counter += 1
        inv_id = f"INV-{inv_id_counter}"; inv_id_counter += 1

        # Two candidate settlements with very similar amounts — genuinely ambiguous
        stl_id_a = f"stl_{stl_id_counter}"; stl_id_counter += 1
        stl_id_b = f"stl_{stl_id_counter}"; stl_id_counter += 1

        amount_b = money(amount - random.choice([0, 5, 10]))  # near-identical decoy

        payments.append([pay_id, amount, d.isoformat(), ref, vendor])
        settlements.append([stl_id_a, amount, d.isoformat(), ref])
        settlements.append([stl_id_b, amount_b, d.isoformat(), ref[:-1] + "9"])
        ledger.append([inv_id, amount, d.isoformat(), customer, vendor])

        # Ground truth still records the TRUE correct match (stl_id_a),
        # but this is where the matcher is expected to need AI/exception handling
        ground_truth.append([pay_id, stl_id_a, inv_id, "MATCH", "ambiguous_duplicate_candidate"])

    # ---------- write files ----------
    with open(f"{out_dir}/payments.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "amount", "date", "customer_ref", "vendor"])
        w.writerows(payments)

    with open(f"{out_dir}/settlements.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["settlement_id", "amount", "date", "reference"])
        w.writerows(settlements)

    with open(f"{out_dir}/ledger.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["invoice", "amount", "date", "customer", "vendor"])
        w.writerows(ledger)

    with open(f"{out_dir}/ground_truth.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "settlement_id", "invoice_id", "label", "case_type"])
        w.writerows(ground_truth)

    with open(f"{out_dir}/vendor_aliases.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["canonical_vendor", "alias_pattern"])
        for vendor, aliases in VENDOR_ALIASES.items():
            for alias in aliases:
                w.writerow([vendor, alias])

    print(f"Generated {len(payments)} payments, {len(settlements)} settlements, "
          f"{len(ledger)} ledger entries -> {out_dir}/")
    print(f"Ground truth: {len(ground_truth)} labeled cases "
          f"({n_clean} clean, {n_noisy} noisy, {n_exception} exceptions, "
          f"{n_duplicate} ambiguous)")
    print(f"Total distinct transaction cases: {total}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate LedgerLens synthetic data")
    parser.add_argument("--scale", type=float, default=1.0,
                         help="Multiplier on base record counts (e.g. 3.0 for ~360 records)")
    parser.add_argument("--output-dir", type=str, default=None,
                         help="Where to write CSVs (default: data/)")
    args = parser.parse_args()
    generate(scale=args.scale, output_dir=args.output_dir)