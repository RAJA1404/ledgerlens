"""
Collects benchmark metrics from ground_truth.csv files produced by --regenerate runs.
Called by the GitHub Actions benchmark workflow after scale tests complete.
"""
import csv
import json
from pathlib import Path

results = {}

# These tests run with --skip-ai so ai_resolver_results.csv is never written.
# Read ground_truth.csv (always present after --regenerate) to get record counts
# and the expected number of MATCH cases.
for scale_dir, scale_name in [
    ("data_baseline", "baseline_1.0x"),
    ("data_medium",   "medium_3.0x"),
    ("data_large",    "large_10.0x"),
]:
    gt_path = Path(f"{scale_dir}/ground_truth.csv")
    if gt_path.exists():
        try:
            with open(gt_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = [r for r in reader if r.get("payment_id") != "NONE"]
                if rows:
                    matched = sum(1 for r in rows if r.get("label") == "MATCH")
                    results[scale_name] = {
                        "records": len(rows),
                        "matched": matched,
                        "match_rate": 100 * matched / len(rows),
                    }
        except Exception as e:
            print(f"WARNING: Error reading {gt_path}: {e}")
    else:
        print(f"SKIP: {scale_name} - ground_truth.csv not found at {gt_path}")

Path("benchmark_results").mkdir(exist_ok=True)

if results:
    with open("benchmark_results/metrics.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("=== BENCHMARK RESULTS ===")
    for test, data in results.items():
        print(f"\n{test}:")
        print(f"  Records:    {data['records']}")
        print(f"  Matched:    {data['matched']}")
        print(f"  Match Rate: {data['match_rate']:.1f}%")
else:
    print("WARNING: No benchmark results found - first run or tests failed")
    # Create empty file so the upload-artifact step does not fail
    with open("benchmark_results/metrics.json", "w", encoding="utf-8") as f:
        json.dump({}, f)
