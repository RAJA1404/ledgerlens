

import argparse
import subprocess
import sys
import os

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")


def run_step(script_name: str, description: str, extra_args=None):
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"{'=' * 60}")
    cmd = [sys.executable, os.path.join(SRC_DIR, script_name)]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    if result.returncode != 0:
        print(f"\n✗ {script_name} failed — stopping pipeline.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run the LedgerLens reconciliation pipeline")
    parser.add_argument("--regenerate", action="store_true",
                         help="Regenerate synthetic data from scratch (same seed, same output)")
    parser.add_argument("--skip-ai", action="store_true",
                         help="Skip the AI resolver step (deterministic-only, no API calls/cost)")
    parser.add_argument("--scale", type=float, default=1.0,
                         help="Data size multiplier when regenerating (e.g. 3.0 for ~360 records)")
    parser.add_argument("--data-dir", type=str, default="data",
                         help="Data directory to use/generate (e.g. data_scale_test for a scale run)")
    parser.add_argument("--batch-size", type=int, default=3,
                         help="Payments per AI resolver API call (default 3, "
                              "safe for free-tier rate limits). Higher = fewer "
                              "calls but bigger prompts.")
    parser.add_argument("--pause-seconds", type=int, default=15,
                         help="Seconds between AI resolver batches (default 15). "
                              "Increase if you hit 429 rate-limit errors.")
    args = parser.parse_args()
    dd = ["--data-dir", args.data_dir]

    if args.regenerate:
        run_step("generate_data.py", "STEP 1: Generating synthetic data",
                  extra_args=["--scale", str(args.scale), "--output-dir", args.data_dir])

    run_step("normalize.py", "STEP 2: Normalizing data (sanity check)", extra_args=dd)
    run_step("deterministic_match.py", "STEP 3: Deterministic matching", extra_args=dd)

    if not args.skip_ai:
        run_step("ai_resolver.py", "STEP 4: AI resolver (calls Gemini API)",
                  extra_args=dd + ["--batch-size", str(args.batch_size),
                                    "--pause-seconds", str(args.pause_seconds)])
    else:
        print("\nSkipping AI resolver (--skip-ai) — evaluation will run on "
              "deterministic-only results, or reuse any previously cached "
              "AI results if present.")

    run_step("evaluate.py", "STEP 5: Final benchmark evaluation", extra_args=dd)

    print(f"\n{'=' * 60}")
    print("Pipeline complete. See benchmark results above.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()