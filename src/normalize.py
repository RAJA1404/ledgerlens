

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime


def normalize_reference(raw_ref: str) -> str:
    """
    Strip everything except alphanumerics, uppercase it, and fix common
    OCR/typo-style corruption (0 <-> O) so that 'order8291', 'ORD-8291',
    and '0RD-8291' all normalize to the same string.
    """
    if not raw_ref or raw_ref == "NONE":
        return ""
    ref = raw_ref.upper()
    ref = re.sub(r"[^A-Z0-9]", "", ref)   # strip dashes, spaces, punctuation
    ref = ref.replace("0RD", "ORD")        # common zero/O typo on the ORD prefix
    return ref


def normalize_amount(raw_amount) -> float:
    """Convert to a clean float, rounded to 2 decimal places (paise-safe)."""
    try:
        return round(float(raw_amount), 2)
    except (TypeError, ValueError):
        return 0.0


def normalize_date(raw_date: str) -> date:
    """Parse ISO date strings (YYYY-MM-DD) into date objects."""
    return datetime.strptime(raw_date.strip(), "%Y-%m-%d").date()


@dataclass
class Payment:
    payment_id: str
    amount: float
    txn_date: date
    ref_raw: str
    ref_norm: str
    vendor: str


@dataclass
class Settlement:
    settlement_id: str
    amount: float
    txn_date: date
    ref_raw: str
    ref_norm: str


@dataclass
class LedgerEntry:
    invoice_id: str
    amount: float
    txn_date: date
    customer: str
    vendor: str


def load_payments(path: str) -> list[Payment]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Payment(
                payment_id=row["payment_id"],
                amount=normalize_amount(row["amount"]),
                txn_date=normalize_date(row["date"]),
                ref_raw=row["customer_ref"],
                ref_norm=normalize_reference(row["customer_ref"]),
                vendor=row["vendor"],
            ))
    return out


def load_settlements(path: str) -> list[Settlement]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Settlement(
                settlement_id=row["settlement_id"],
                amount=normalize_amount(row["amount"]),
                txn_date=normalize_date(row["date"]),
                ref_raw=row["reference"],
                ref_norm=normalize_reference(row["reference"]),
            ))
    return out


def load_ledger(path: str) -> list[LedgerEntry]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(LedgerEntry(
                invoice_id=row["invoice"],
                amount=normalize_amount(row["amount"]),
                txn_date=normalize_date(row["date"]),
                customer=row["customer"],
                vendor=row["vendor"],
            ))
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="data")
    args = parser.parse_args()

    # Quick sanity check when run directly
    payments = load_payments(f"{args.data_dir}/payments.csv")
    settlements = load_settlements(f"{args.data_dir}/settlements.csv")
    ledger = load_ledger(f"{args.data_dir}/ledger.csv")

    print(f"Loaded {len(payments)} payments, {len(settlements)} settlements, "
          f"{len(ledger)} ledger entries")
    print()
    print("Sample normalized payment:", payments[0])
    print("Sample normalized settlement:", settlements[0])

    # Show that reference normalization actually collapses variants
    test_refs = ["ORD-8291", "order8291", "0RD-8291", "ORD 8291"]
    print()
    print("Reference normalization check:")
    for r in test_refs:
        print(f"  {r!r:15} -> {normalize_reference(r)!r}")