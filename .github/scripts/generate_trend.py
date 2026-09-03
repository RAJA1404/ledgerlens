"""
Generates a benchmark trend markdown report from historical metrics JSON files.
Called by the GitHub Actions compare_benchmarks job.
"""
import json
from pathlib import Path

history_dir = Path(".github/benchmark_history")
data_points = []

if history_dir.exists():
    for file in sorted(history_dir.glob("*.json")):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)
                data["date"] = file.stem
                data_points.append(data)
        except Exception as e:
            print(f"WARNING: Error reading {file}: {e}")

with open("BENCHMARK_TREND.md", "w", encoding="utf-8") as f:
    f.write("# Benchmark Trend Analysis\n\n")
    if data_points:
        f.write("## Historical Performance\n\n")
        for point in data_points[-10:]:  # Last 10 benchmarks
            if "baseline_1.0x" in point:
                records = point["baseline_1.0x"]["records"]
                rate = point["baseline_1.0x"]["match_rate"]
                f.write(f"- **{point['date']}**: {records} records, {rate:.1f}% match rate\n")
        print("Benchmark trend report generated.")
    else:
        f.write("No historical data available yet.\n")
        print("INFO: No benchmark history yet - will populate after first benchmark run.")
